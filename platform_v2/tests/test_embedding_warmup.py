"""#6648 — embedding models have no generate head, and bare tags never matched.

TWO INDEPENDENT DEFECTS that multiplied each other:

1. `load_model` warmed EVERY model by POSTing `/api/generate`. `arctic-embed-cpu` is a
   custom Modelfile `FROM snowflake-arctic-embed:m` — a BERT encoder with no generate
   head — so Ollama answered
       HTTP 400 {"error":"\\"arctic-embed-cpu\\" does not support generate"}
   on every warm-up.

2. The residency short-circuit compared exactly: `if m.get("name") == model:`. Ollama's
   /api/ps reports `arctic-embed-cpu:latest`, while callers pass the bare
   `arctic-embed-cpu` (the OLLAMA_EMBEDDING_MODEL default). The bare tag therefore NEVER
   matched a model sitting warm in RAM, so every call fell through to the warm-boot —
   where defect 1 fired.

Measured back-to-back against the SAME resident model:
    ensure_model_ready('arctic-embed-cpu:latest') -> ready=True,  tier='cpu',  0.00s
    ensure_model_ready('arctic-embed-cpu')        -> ready=False, tier='cold', 0.28s + 400

It went unnoticed because `semantic_scanner.cosine_similarity` wrapped the warm-up in a
bare `except Exception: pass`.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_embedding_warmup.py -v
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import model_service as ms  # noqa: E402


# ── defect 1: endpoint selection ─────────────────────────────────────────────


def test_known_embedding_models_are_detected():
    for name in (
        "arctic-embed-cpu",
        "arctic-embed-cpu:latest",
        "snowflake-arctic-embed:m",
        "nomic-embed-text",
        "bge-large",
        "gte-base",
    ):
        assert ms.is_embedding_model(name), f"{name} should be detected as an embedding model"


def test_generative_models_are_NOT_detected():
    """The expensive false positive: warming a chat model on /api/embed would break it.

    Every model in the live warm set must be classified generative.
    """
    for name in (
        "qwen2.5:7b",
        "qwen2.5-coder:7b",
        "qwen25-classify",
        "mistral:7b",
        "gemma3:12b",
        "dolphin3:latest",
        "phi4:14b",
        "llama3.2:3b",
        "minicpm-v-cpu:latest",
        "translategemma:4b",
        "qwen3-coder:30b",
    ):
        assert not ms.is_embedding_model(name), f"{name} must NOT be treated as an embedding model"


def test_load_model_branches_on_the_endpoint():
    src = inspect.getsource(ms.ModelService.load_model)
    assert "is_embedding_model(model)" in src, "load_model must branch on model family"
    assert "/api/embed" in src, "embedding models must warm via /api/embed"
    assert "generate" in src, "generative models must still use /api/generate"


def test_unload_model_branches_too():
    """unload_model has the SAME /api/generate bug, and it is called from
    ensure_capacity's eviction loop — a failed eviction never frees the RAM."""
    src = inspect.getsource(ms.ModelService.unload_model)
    assert "is_embedding_model(model)" in src
    assert "/api/embed" in src


def test_behaviour_overrides_the_name_heuristic():
    """`is_embedding_model` is a NAME check and can be wrong. A real 400 saying
    'does not support generate' must trigger a retry on /api/embed, so a future
    model named e.g. 'embedder-chat' cannot silently fail every warm-up."""
    src = inspect.getsource(ms.ModelService.load_model)
    assert "does not support generate" in src, "must fall back on the server's own answer"
    assert "exc.code == 400" in src


# ── defect 2: tag normalization ──────────────────────────────────────────────


def test_bare_tag_matches_latest():
    assert ms._same_model_tag("arctic-embed-cpu:latest", "arctic-embed-cpu")
    assert ms._same_model_tag("arctic-embed-cpu", "arctic-embed-cpu:latest")
    assert ms._same_model_tag("qwen2.5:7b", "qwen2.5:7b")


def test_different_models_still_do_not_match():
    """The over-correction guard — normalization must not collapse distinct models."""
    assert not ms._same_model_tag("qwen2.5:7b", "qwen2.5:1.5b")
    assert not ms._same_model_tag("arctic-embed-cpu", "nomic-embed-text")
    assert not ms._same_model_tag("gemma3:12b", "gemma3:4b")
    assert not ms._same_model_tag("", "qwen2.5:7b")


def test_residency_check_uses_the_normalized_compare():
    src = inspect.getsource(ms.ModelService._ensure_model_ready_locked)
    assert "_same_model_tag(" in src, "the residency short-circuit must be tag-normalized"
    assert 'm.get("name") == model' not in src, "the exact compare must be gone"


# ── the swallowed warm-up ────────────────────────────────────────────────────


def test_scanner_warmup_failure_is_no_longer_silent():
    from tools.consciousness.translation_scanners import semantic_scanner as ss

    src = inspect.getsource(ss.cosine_similarity)
    assert "except Exception: pass" not in src.replace("\n", " "), "the bare pass must be gone"
    assert "_warmup_warned" in src, "must warn once per process"
    assert hasattr(ss, "logger"), "module needs a logger, or the warning path NameErrors"
    assert hasattr(ss, "_warmup_warned"), "module-level flag must exist"


def test_scanner_warns_once_not_per_call(monkeypatch, caplog):
    """~1,081 calls a night — a per-call WARNING would replace a silent bug with an
    unreadable log."""
    import logging

    from tools.consciousness.translation_scanners import semantic_scanner as ss

    monkeypatch.setattr(ss, "_warmup_warned", False, raising=False)

    def boom():
        raise RuntimeError("simulated warm-up failure")

    monkeypatch.setattr(ss, "generate_embedding", lambda t: [], raising=False)
    import services.model_service as _ms

    monkeypatch.setattr(_ms, "get_model_service", boom, raising=True)

    with caplog.at_level(logging.WARNING, logger="agent_loop"):
        ss.cosine_similarity("a", "b")
        ss.cosine_similarity("c", "d")
        ss.cosine_similarity("e", "f")

    warns = [r for r in caplog.records if "warm-up failed" in r.getMessage()]
    assert len(warns) == 1, f"expected exactly ONE warning across 3 calls, got {len(warns)}"
