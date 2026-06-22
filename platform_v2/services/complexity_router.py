"""Complexity-aware model right-sizing (P2-B, project #381).

Estimates task complexity 0-10 and recommends the smallest CAPABLE model so trivial work doesn't
burn a 7B. Today the dispatcher routes capability -> agent -> agent's model with NO complexity gate.

CONSERVATIVE by design: only an explicit allowlist of *downgradeable* capabilities is ever right-sized
(reasoning / code / research / security keep their model regardless of prompt length). The live wiring
is flag-gated ``complexity_routing_enabled`` (default OFF) — rollout is owner-gated, consistent with the
Phase-2 'Tier-2 gate model changes' decision: validate downgrades against P2-A correctness grades before
enabling. Pure functions here = unit-testable without a dispatch.
"""

# Capabilities safe to downgrade to a small model when the prompt is simple. Reasoning / code /
# research / security / debug are EXCLUDED — they keep their default model regardless of length.
_DOWNGRADEABLE = {
    "classify",
    "summarize",
    "summarization",
    "translate",
    "notification",
    "format",
    "lightweight",
    "support",
}

# Models that exist in the hub warm set (ai-bridge.md). Ascending capability.
_TINY_MODEL = "qwen2.5:1.5b"  # 1.5B — only the most trivial
_SMALL_MODEL = "llama3.2:3b"  # 3B — safe floor for simple language tasks

# Capabilities that are inherently non-trivial — bias their complexity up so they never downgrade.
_HEAVY_CAPABILITIES = {"code", "code_review", "research", "knowledge_analysis", "security", "debug"}

_COMPLEX_KW = (
    "architecture",
    "design",
    "refactor",
    "debug",
    "race condition",
    "security",
    "vulnerability",
    "across",
    "entire",
    "step by step",
    "prove",
    "reason through",
    "trade-off",
)


def estimate_complexity(prompt: str, capability: str = "") -> int:
    """Heuristic task complexity 0-10 (length + complexity keywords + capability base). Pure."""
    if not prompt:
        return 0
    p = prompt.lower()
    n = len(prompt)
    score = 0 if n < 200 else 2 if n < 800 else 4 if n < 2500 else 6
    score += sum(1 for kw in _COMPLEX_KW if kw in p)
    if capability in _HEAVY_CAPABILITIES:
        score += 3
    return max(0, min(10, score))


def right_size_model(capability: str, prompt: str, threshold: int = 3):
    """Return a SMALLER model name for a downgradeable capability at low complexity, else None.
    Conservative: only the ``_DOWNGRADEABLE`` allowlist; never touches code/research/security/etc."""
    if capability not in _DOWNGRADEABLE:
        return None
    c = estimate_complexity(prompt, capability)
    if c <= 1:
        return _TINY_MODEL
    if c <= threshold:
        return _SMALL_MODEL
    return None
