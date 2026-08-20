"""A pinned dispatch must check the model is PRESENT, not just that it FITS (#5863/#5861).

THE BUG: `can_node_run_model` is capacity-only. For USS-245 and qwen2.5-coder:7b it returns
True — the GPU path fails (needs 5.5GB vram, node has 4.0), so it falls through to
`cap = ram_gb = 11.7`, `required = 8.0`, and 8.0 <= 11.7 deems CPU demotion viable. But the
model is not pulled on that node, so every dispatch died instantly: measured 2026-08-20,
16 runs / 0 ok / ~0.3s each / MODEL_NOT_FOUND.

`node_has_model` already existed (written for #4272) and already guards the SELECTION path
inside `find_best_node_for_model`. The PINNED path checked only capacity. The guard was
right; it simply was not wired at that choke point — the same shape as #5194 and #5862.

⚠️ The presence gate is FAIL-OPEN by design. Wrongly allowing costs one fast failure;
wrongly blocking could starve the dispatch queue. Those are not symmetric, and the tests
below pin that asymmetry.
"""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.fleet_resource_router import (  # noqa: E402
    can_node_run_model,
    node_has_model,
)

# Shaped from the real rows, measured 2026-08-20.
USS245 = {
    "node_id": "starship_245",
    "node_name": "Starship - Runabout - USS-245",
    "gpu_available": True,
    "gpu_vram_gb": 4.0,
    "ram_gb": 11.7,
    "extra_capabilities": {"ollama_models": ["qwen2.5:1.5b", "llama3.2:3b", "qwen2.5:7b", "mistral:7b"]},
}
USS246 = {
    "node_id": "starship_246",
    "node_name": "Starship - Defiant - USS-246",
    "gpu_available": True,
    "gpu_vram_gb": 8.0,
    "ram_gb": 29.4,
    "extra_capabilities": {"ollama_models": ["qwen2.5:7b", "qwen2.5-coder:7b", "llama3.2:3b"]},
}


class TestCapacityIsNotPresence(unittest.TestCase):
    def test_the_exact_live_defect(self):
        """Capacity says yes, presence says no — and presence is what mattered."""
        self.assertTrue(
            can_node_run_model(USS245, "qwen2.5-coder:7b"),
            "if this flips, the premise of the fix changed — re-measure before trusting it",
        )
        self.assertFalse(
            node_has_model(USS245, "qwen2.5-coder:7b"),
            "USS-245 does not have coder:7b pulled; this is the 0/16 failure",
        )

    def test_a_node_that_genuinely_has_it_passes_both(self):
        self.assertTrue(can_node_run_model(USS246, "qwen2.5-coder:7b"))
        self.assertTrue(node_has_model(USS246, "qwen2.5-coder:7b"))

    def test_model_the_node_does_have_is_allowed(self):
        self.assertTrue(node_has_model(USS245, "qwen2.5:7b"))


class TestFailOpen(unittest.TestCase):
    """Unknown inventory must NEVER disqualify a node."""

    def test_missing_model_list_allows(self):
        node = dict(USS245, extra_capabilities={})
        self.assertTrue(node_has_model(node, "qwen2.5-coder:7b"))

    def test_empty_model_list_allows(self):
        node = dict(USS245, extra_capabilities={"ollama_models": []})
        self.assertTrue(node_has_model(node, "qwen2.5-coder:7b"))

    def test_non_dict_extra_capabilities_allows(self):
        node = dict(USS245, extra_capabilities="not-a-dict")
        self.assertTrue(node_has_model(node, "qwen2.5-coder:7b"))


class TestPinnedPathIsWired(unittest.TestCase):
    """The guard existed and was correct — it just was not called here."""

    def test_pinned_dispatch_calls_the_presence_gate(self):
        import services.model_dispatch_service as mds

        src = inspect.getsource(mds)
        self.assertIn("node_has_model", src, "the pinned path must check presence, not only capacity")
        self.assertIn("presence gate", src, "a refusal must say WHY it refused")

    def test_selection_path_still_pairs_both_predicates(self):
        """Regression guard: don't 'tidy' the pairing out of find_best_node_for_model."""
        import services.fleet_resource_router as frr

        src = inspect.getsource(frr.find_best_node_for_model)
        self.assertIn("can_node_run_model", src)
        self.assertIn("node_has_model", src)


if __name__ == "__main__":
    unittest.main()
