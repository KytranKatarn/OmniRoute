"""The media drain must not execute work welfare has refused (#5345 / #5211 step 2a).

`_media_generation_worker` asked DHQ for an image_generation agent, and on a miss
logged "proceeding anyway" and ran regardless — attributing the work to a hardcoded
fallback (agent_id 13, "P.I.X.E.L."). That is the ADR-002 bypass in miniature: a
drain executing with no welfare, C.R.E.E.D. or cost gating.

`coordinator.select_agent` ALREADY scores candidates on stress / energy /
utilisation and returns None when nothing qualifies, so a None IS the welfare
verdict. Making the advisory selection BINDING is therefore the whole gate — no new
machinery.

⚠️ THE TRAP THIS FILE ALSO GUARDS. The task text implied the drain had no
attribution. It does: THREE task_execution_log writes, one of them an explicit
INSERT (agent_id, agent_name, model_used, duration_ms, success, capability,
node_used_id, module_source) with capability='image_generation'. Adding
`log_marker` "for attribution" would DOUBLE-COUNT image generation on the Token
Economy and A.R.M.A.D.A. surfaces — turning an accounting-integrity task into an
accounting-integrity bug. The count assertions below exist to catch that.
"""

import ast
import os
import re

import pytest

# Read the method's SOURCE from disk rather than via `inspect.getsource` on an imported
# module (#5665). Other test modules install a stub at sys.modules["ai_bridge.agent_loop"]
# at import time, and a stub cannot yield source — so in a full-suite run this file died
# with `AttributeError: module 'ai_bridge.agent_loop' has no attribute 'AgentLoop'`, and a
# collection error aborts ALL 3,337 tests. It passed alone (11 passed), which is exactly
# what made it easy to miss.
# Reading the file keeps the test running in EVERY order instead of skipping it, and this
# test only ever wanted the source text.
_CANDIDATES = [
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ai_bridge", "agent_loop.py"
    ),
    "/mnt/archie_brain/ai_bridge/agent_loop.py",
]
_AGENT_LOOP_PY = next((c for c in _CANDIDATES if os.path.isfile(c)), None)
if _AGENT_LOOP_PY is None:  # pragma: no cover - environment-dependent
    pytest.skip(f"ai_bridge/agent_loop.py not found (looked in {_CANDIDATES})", allow_module_level=True)

with open(_AGENT_LOOP_PY, "r", encoding="utf-8") as _fh:
    _AGENT_LOOP_SRC = _fh.read()


def _method_source(class_name: str, method_name: str) -> str:
    """Exact source of ``class_name.method_name`` — import-state independent."""
    tree = ast.parse(_AGENT_LOOP_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == method_name:
                    return ast.get_source_segment(_AGENT_LOOP_SRC, sub) or ""
    raise AssertionError(f"{class_name}.{method_name} not found in {_AGENT_LOOP_PY}")


SRC = _method_source("AgentLoop", "_media_generation_worker")


class TestWelfareRefusalDefers:
    def test_no_agent_sets_the_defer_flag_instead_of_proceeding(self):
        assert "_dhq_defer = True" in SRC
        assert "proceeding anyway" not in SRC, "the old behaviour ran the drain regardless of the welfare verdict"

    def test_defer_flag_is_initialised_falsy(self):
        """An unset flag must never read as 'defer' and stall the queue."""
        assert "_dhq_defer = False" in SRC
        assert SRC.index("_dhq_defer = False") < SRC.index("_dhq_defer = True")

    def test_deferral_returns_without_claiming(self):
        m = re.search(r"if _dhq_defer:(.*?)return", SRC, re.S)
        assert m, "no deferral guard found"
        block = m.group(0)
        assert (
            "UPDATE media_generation_queue" not in block
        ), "deferring must NOT claim rows — they stay 'pending' for the next cycle"
        assert "status = 'failed'" not in block, "deferring is not failing"

    def test_guard_sits_before_the_claim(self):
        """Rows must stay pending, so the gate precedes the claim UPDATE."""
        assert SRC.index("if _dhq_defer:") < SRC.index("UPDATE media_generation_queue")

    def test_deferral_still_reclaims_vram(self):
        """A deferral must not leave ComfyUI resident holding VRAM.

        The normal idle-stop lives in the `if not claimed:` branch AFTER the claim,
        so an early return would skip it — caught by this test on the first draft of
        the fix. Deferring means we generate nothing, which is exactly when the
        container should be down (#5277). The defer branch therefore idle-stops on
        its way out, best-effort.
        """
        m = re.search(r"if _dhq_defer:(.*?)return", SRC, re.S)
        assert m, "no deferral guard found"
        assert "stop_if_idle" in m.group(1), "deferring skips the post-claim idle-stop, so it must reclaim VRAM itself"

    def test_idle_stop_on_defer_cannot_raise(self):
        """A telemetry/infra hiccup must not turn a clean deferral into an error."""
        m = re.search(r"if _dhq_defer:(.*?)return", SRC, re.S)
        assert "except Exception" in m.group(1)


class TestAnErrorIsNotARefusal:
    """A coordinator fault must not stall ALL image generation."""

    def test_lookup_exception_does_not_set_defer(self):
        m = re.search(r"except Exception as dhq_err:(.*?)(?=\n        [#\w])", SRC, re.S)
        assert m, "DHQ lookup except block not found"
        assert "_dhq_defer" not in m.group(1), (
            "an infrastructure error is not a capacity verdict — fail OPEN, or one "
            "bug stalls the whole queue indefinitely"
        )

    def test_the_distinction_is_documented(self):
        assert "ERROR is not a" in SRC or "error is not a" in SRC.lower()


class TestAttributionIsNotDuplicated:
    """THE #5345 TRAP: attribution already exists. Do not add a second writer."""

    def test_existing_task_execution_log_writes_are_preserved(self):
        assert SRC.count("task_execution_log") == 3, (
            "the drain already writes attribution; changing this count means either "
            "a write was lost or a duplicate was introduced"
        )

    def test_no_log_marker_was_added(self):
        assert "log_marker" not in SRC, (
            "log_marker here would DOUBLE-COUNT image generation — the drain already "
            "INSERTs its own row with capability='image_generation'"
        )

    def test_the_existing_insert_still_carries_full_attribution(self):
        for col in ("agent_id", "agent_name", "model_used", "capability", "node_used_id", "module_source"):
            assert col in SRC, f"attribution column {col} disappeared"
        assert "image_generation" in SRC
