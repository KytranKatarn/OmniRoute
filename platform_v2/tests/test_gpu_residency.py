"""Pin the GPU-to-model attribution contract.

These tests exist because the obvious validation was VACUOUS. Sampling the live
hub six times only ever found ONE GPU-resident model, so a "nearest match wins"
matcher scored 6/6 without ever being asked to tell two models apart -- which is
the only question that matters. Disambiguation is therefore pinned here, with
synthetic inputs that actually contain the ambiguity.

Every test that asserts a REFUSAL also asserts that a naive nearest-match
implementation would have answered confidently and wrongly, so the test cannot
quietly become tautological if the matcher is rewritten.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.department_hq.services import gpu_residency as gr  # noqa: E402

MIB = 1048576
GB = 10**9

QUADRO = "GPU-e20b1ba4-f652-6e4f-92c5-15e359a8de1b"
TITAN = "GPU-93e51659-be75-1c64-2d85-30f084a29023"


def _naive(models, procs):
    """What a careless implementation does: nearest proc always wins.

    Used only to prove the refusal tests are discriminating.
    """
    out = {}
    for m in models:
        if not m.get("size_vram"):
            continue
        best = min(procs, key=lambda p: abs(p["bytes"] - m["size_vram"]))
        out[m["name"]] = best["uuid"]
    return out


class TestForcedAssignments(unittest.TestCase):
    def test_single_model_single_process_is_attributed(self):
        models = [{"name": "mistral:7b", "size_vram": 5_140_119_552}]
        procs = [{"pid": "100", "bytes": 4902 * MIB, "uuid": TITAN}]
        r = gr.attribute(models, procs)
        self.assertTrue(r["available"])
        self.assertEqual([m["name"] for m in r["by_uuid"][TITAN]], ["mistral:7b"])
        self.assertEqual(r["unresolved"], [])

    def test_two_clearly_different_models_both_attributed(self):
        models = [
            {"name": "qwen2.5:1.5b", "size_vram": 1_300_000_000},
            {"name": "gemma3:12b", "size_vram": 9_000_000_000},
        ]
        procs = [
            {"pid": "1", "bytes": 1_350_000_000, "uuid": QUADRO},
            {"pid": "2", "bytes": 9_200_000_000, "uuid": TITAN},
        ]
        r = gr.attribute(models, procs)
        self.assertEqual(r["unresolved"], [])
        self.assertEqual([m["name"] for m in r["by_uuid"][QUADRO]], ["qwen2.5:1.5b"])
        self.assertEqual([m["name"] for m in r["by_uuid"][TITAN]], ["gemma3:12b"])

    def test_cuda_overhead_above_model_size_still_matches(self):
        """A process holds weights PLUS context/KV -- it is legitimately bigger."""
        models = [{"name": "qwen2.5:7b", "size_vram": 4_920_000_000}]
        procs = [{"pid": "9", "bytes": 4_920_000_000 + 100 * MIB, "uuid": QUADRO}]
        r = gr.attribute(models, procs)
        self.assertEqual([m["name"] for m in r["by_uuid"][QUADRO]], ["qwen2.5:7b"])


class TestRefusals(unittest.TestCase):
    def test_two_same_sized_models_are_BOTH_unresolved(self):
        """The whole point. Two 7B models at the same quant are indistinguishable
        by bytes, so neither may be pinned to a card."""
        models = [
            {"name": "qwen2.5:7b", "size_vram": 4_920_000_000},
            {"name": "qwen2.5-coder:7b", "size_vram": 4_925_000_000},
        ]
        procs = [
            {"pid": "1", "bytes": 4_930_000_000, "uuid": QUADRO},
            {"pid": "2", "bytes": 4_918_000_000, "uuid": TITAN},
        ]
        r = gr.attribute(models, procs)
        self.assertEqual(r["unresolved"], ["qwen2.5-coder:7b", "qwen2.5:7b"], r["by_uuid"])
        self.assertEqual(r["by_uuid"], {})

        # Non-vacuity: a naive matcher answers confidently here, and its answer
        # is a coin flip presented as fact.
        naive = _naive(models, procs)
        self.assertEqual(len(naive), 2)
        self.assertIn(naive["qwen2.5:7b"], (QUADRO, TITAN))

    def test_extra_cuda_process_near_a_model_blocks_attribution(self):
        """A non-Ollama CUDA process (ComfyUI, say) that happens to sit near a
        model's footprint makes the pairing ambiguous."""
        models = [{"name": "mistral:7b", "size_vram": 5_140_000_000}]
        procs = [
            {"pid": "1", "bytes": 5_150_000_000, "uuid": QUADRO},
            {"pid": "2", "bytes": 5_130_000_000, "uuid": TITAN},
        ]
        r = gr.attribute(models, procs)
        self.assertEqual(r["unresolved"], ["mistral:7b"])
        self.assertEqual(r["by_uuid"], {})
        self.assertEqual(len(_naive(models, procs)), 1)  # naive would pick one

    def test_model_with_no_matching_process_is_unresolved_not_dropped(self):
        """A resident model must still be reported even with no pid to pin it to."""
        models = [{"name": "dolphin3:latest", "size_vram": 5_690_000_000}]
        procs = [{"pid": "1", "bytes": 500 * MIB, "uuid": QUADRO}]
        r = gr.attribute(models, procs)
        self.assertEqual(r["unresolved"], ["dolphin3:latest"])
        self.assertTrue(r["available"])


class TestUnknownVsEmpty(unittest.TestCase):
    def test_nvidia_smi_unavailable_is_UNKNOWN_not_empty_cards(self):
        """ADR-017: an unknown is reported as unknown. Returning empty cards here
        would render as 'both GPUs idle' while models are resident on them."""
        models = [{"name": "mistral:7b", "size_vram": 5_140_000_000}]
        r = gr.attribute(models, None)
        self.assertFalse(r["available"])
        self.assertEqual(r["unresolved"], ["mistral:7b"])
        self.assertEqual(r["by_uuid"], {})

    def test_cpu_only_models_are_not_gpu_candidates(self):
        models = [
            {"name": "arctic-embed-cpu:latest", "size_vram": 0},
            {"name": "dolphin3-8k:latest", "size_vram": 0},
        ]
        procs = [{"pid": "1", "bytes": 5 * GB, "uuid": QUADRO}]
        r = gr.attribute(models, procs)
        self.assertEqual(r["by_uuid"], {})
        self.assertEqual(r["unresolved"], [])

    def test_no_models_resident_yields_nothing_claimed(self):
        r = gr.attribute([], [{"pid": "1", "bytes": 5 * GB, "uuid": QUADRO}])
        self.assertEqual(r["by_uuid"], {})
        self.assertEqual(r["unresolved"], [])


class TestLoadedCardIsNeverIdle(unittest.TestCase):
    """The LIVE hub state on 2026-09-20, which is the reason this exists.

    /api/ps reported qwen2.5:7b and qwen2.5-coder:7b with BYTE-IDENTICAL
    size_vram (4.92 GB each) plus mistral:7b at 5.14 GB, against three
    processes at 7.32 GB (spanning), 5.14 GB and 5.11 GB. No assignment is
    forced, so nothing is named -- correctly. But the first version of this
    work then rendered a Quadro holding 6.8/8 GB as "idle", which is simply
    false. Unnamed allocations must survive to the caller.
    """

    def test_unattributable_allocations_are_still_reported_per_card(self):
        models = [
            {"name": "qwen2.5:7b", "size_vram": 4_920_000_000},
            {"name": "qwen2.5-coder:7b", "size_vram": 4_920_000_000},
            {"name": "mistral:7b", "size_vram": 5_140_000_000},
        ]
        procs = [
            {"pid": "3866636", "bytes": 7_180_000_000, "uuid": QUADRO},
            {"pid": "3866636", "bytes": 140_000_000, "uuid": TITAN},
            {"pid": "3900752", "bytes": 5_140_000_000, "uuid": TITAN},
            {"pid": "3901619", "bytes": 5_110_000_000, "uuid": TITAN},
        ]
        r = gr.attribute(models, procs)

        # Nothing may be named: the two 7B models are indistinguishable.
        self.assertEqual(r["by_uuid"], {})
        self.assertEqual(len(r["unresolved"]), 3)

        # ...but the Quadro's 7.18 GB must NOT vanish.
        self.assertIn(QUADRO, r["anon_by_uuid"])
        self.assertEqual(r["anon_by_uuid"][QUADRO][0]["bytes"], 7_180_000_000)
        quadro_total = sum(a["bytes"] for a in r["anon_by_uuid"][QUADRO])
        self.assertGreater(quadro_total, 7 * GB)

    def test_named_and_unnamed_do_not_double_count_the_same_process(self):
        """One pid is either named or unnamed -- never both, or the card's
        occupancy would be reported twice."""
        models = [
            {"name": "tiny:1b", "size_vram": 1_000_000_000},
            {"name": "a:7b", "size_vram": 4_920_000_000},
            {"name": "b:7b", "size_vram": 4_920_000_000},
        ]
        procs = [
            {"pid": "1", "bytes": 1_010_000_000, "uuid": QUADRO},
            {"pid": "2", "bytes": 4_930_000_000, "uuid": TITAN},
            {"pid": "3", "bytes": 4_910_000_000, "uuid": TITAN},
        ]
        r = gr.attribute(models, procs)
        named = {m["name"] for lst in r["by_uuid"].values() for m in lst}
        self.assertEqual(named, {"tiny:1b"})  # only the distinct one is forced
        anon_pids_bytes = sorted(a["bytes"] for lst in r["anon_by_uuid"].values() for a in lst)
        self.assertEqual(anon_pids_bytes, [4_910_000_000, 4_930_000_000])
        # pid 1 was claimed by name, so it must not also appear as unnamed.
        self.assertNotIn(1_010_000_000, anon_pids_bytes)

    def test_unknown_snapshot_reports_no_unnamed_allocations(self):
        r = gr.attribute([{"name": "x:7b", "size_vram": 5 * GB}], None)
        self.assertEqual(r["anon_by_uuid"], {})


class TestSpanning(unittest.TestCase):
    def test_a_model_spanning_two_cards_appears_on_BOTH(self):
        """Ollama splits layers across cards routinely on this hub. The model is
        one pid holding memory on two GPUs; it must not be collapsed onto one."""
        models = [{"name": "gemma3:12b", "size_vram": 11_000_000_000}]
        procs = [
            {"pid": "77", "bytes": 6_000_000_000, "uuid": QUADRO},
            {"pid": "77", "bytes": 5_100_000_000, "uuid": TITAN},
        ]
        r = gr.attribute(models, procs)
        self.assertEqual(r["unresolved"], [])
        self.assertEqual([m["name"] for m in r["by_uuid"][QUADRO]], ["gemma3:12b"])
        self.assertEqual([m["name"] for m in r["by_uuid"][TITAN]], ["gemma3:12b"])
        self.assertEqual(r["by_uuid"][QUADRO][0]["bytes"], 6_000_000_000)
        self.assertEqual(r["by_uuid"][TITAN][0]["bytes"], 5_100_000_000)

    def test_spanning_is_matched_on_the_pid_TOTAL_not_a_single_card(self):
        """Neither card alone is within tolerance of the model; only the sum is.
        A per-card matcher would leave this unresolved."""
        models = [{"name": "gemma3:12b", "size_vram": 11_000_000_000}]
        procs = [
            {"pid": "77", "bytes": 6_000_000_000, "uuid": QUADRO},
            {"pid": "77", "bytes": 5_100_000_000, "uuid": TITAN},
        ]
        for p in procs:
            self.assertGreater(
                abs(p["bytes"] - models[0]["size_vram"]),
                gr._tolerance(models[0]["size_vram"]),
            )
        self.assertEqual(gr.attribute(models, procs)["unresolved"], [])


class TestSnapshotParsing(unittest.TestCase):
    """nvidia-smi emits ONE ROW PER LINE. Splitting the whole payload on ','
    merges rows -- the exact bug this panel shipped once for the per-GPU query."""

    def _fake_run(self, stdout, rc=0):
        class R:
            returncode = rc
            stderr = ""

        R.stdout = stdout
        return lambda *a, **k: R()

    def test_multiple_rows_parse_independently(self):
        real = gr.subprocess.run
        gr.subprocess.run = self._fake_run(f"3788979, 6852, {QUADRO}\n3783820, 4902, {TITAN}\n")
        try:
            snap = gr.gpu_process_snapshot()
        finally:
            gr.subprocess.run = real
        self.assertEqual(len(snap), 2)
        self.assertEqual(snap[0]["bytes"], 6852 * MIB)
        self.assertEqual(snap[1]["uuid"], TITAN)

    def test_nonzero_rc_is_unknown_not_empty(self):
        real = gr.subprocess.run
        gr.subprocess.run = self._fake_run("", rc=9)
        try:
            self.assertIsNone(gr.gpu_process_snapshot())
        finally:
            gr.subprocess.run = real

    def test_no_processes_is_empty_list_not_none(self):
        """nvidia-smi answering with zero rows is a real 'nothing resident',
        which is a different fact from nvidia-smi being absent."""
        real = gr.subprocess.run
        gr.subprocess.run = self._fake_run("\n")
        try:
            self.assertEqual(gr.gpu_process_snapshot(), [])
        finally:
            gr.subprocess.run = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
