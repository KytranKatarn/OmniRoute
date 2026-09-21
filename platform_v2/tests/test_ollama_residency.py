"""Pin the exact PID->model resolution, and the trap it exists to avoid.

A weights blob identifies WEIGHTS, not a model tag. Measured on this hub, 7 of
19 blobs back several tags (a Modelfile variant reuses its base's weights)::

    sha256-...  ->  {qwen2.5:7b, vivid:latest, weave:latest}
    sha256-...  ->  {qwen2.5:1.5b, qwen25-classify:latest}

An early prototype resolved by blob alone and labelled a resident ``qwen2.5:7b``
as ``weave:latest`` -- the same confident-falsehood class this whole area keeps
being fixed for. Narrowing by the resident set fixed it (3 exact, 0 ambiguous on
the live hub). These tests hold that narrowing in place.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ollama_residency import (  # noqa: E402
    blob_from_cmdline,
    manifest_index,
    resolve_model_name,
)

WEIGHTS = "application/vnd.ollama.image.model"
PARAMS = "application/vnd.ollama.image.params"


def _write_manifest(root, namespace, model, tag, weights_digest, extra_layers=()):
    d = os.path.join(root, "manifests", "registry.ollama.ai", namespace, model)
    os.makedirs(d, exist_ok=True)
    layers = [{"mediaType": WEIGHTS, "digest": weights_digest}]
    layers.extend(extra_layers)
    with open(os.path.join(d, tag), "w", encoding="utf-8") as fh:
        json.dump({"schemaVersion": 2, "layers": layers}, fh)


class TestManifestIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_library_namespace_is_dropped_from_the_name(self):
        _write_manifest(self.tmp, "library", "mistral", "7b", "sha256:aaa")
        idx = manifest_index(self.tmp)
        self.assertEqual(idx["sha256-aaa"], {"mistral:7b"})

    def test_non_library_namespace_is_kept(self):
        _write_manifest(self.tmp, "alpernae", "qwen2.5-auditor", "latest", "sha256:bbb")
        idx = manifest_index(self.tmp)
        self.assertEqual(idx["sha256-bbb"], {"alpernae/qwen2.5-auditor:latest"})

    def test_shared_weights_produce_a_SET_not_a_last_writer_wins(self):
        """The measured reality: three tags, one blob."""
        for name in ("qwen2.5", "vivid", "weave"):
            tag = "7b" if name == "qwen2.5" else "latest"
            _write_manifest(self.tmp, "library", name, tag, "sha256:shared")
        idx = manifest_index(self.tmp)
        self.assertEqual(idx["sha256-shared"], {"qwen2.5:7b", "vivid:latest", "weave:latest"})

    def test_only_the_weights_layer_counts(self):
        _write_manifest(
            self.tmp,
            "library",
            "mistral",
            "7b",
            "sha256:weights",
            extra_layers=[{"mediaType": PARAMS, "digest": "sha256:params"}],
        )
        idx = manifest_index(self.tmp)
        self.assertIn("sha256-weights", idx)
        self.assertNotIn("sha256-params", idx)

    def test_a_malformed_manifest_does_not_blind_the_index(self):
        _write_manifest(self.tmp, "library", "good", "1b", "sha256:ok")
        bad = os.path.join(self.tmp, "manifests", "registry.ollama.ai", "library", "bad")
        os.makedirs(bad, exist_ok=True)
        with open(os.path.join(bad, "latest"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        # `layers: null` is real -- it crashed the first prototype.
        nul = os.path.join(self.tmp, "manifests", "registry.ollama.ai", "library", "nul")
        os.makedirs(nul, exist_ok=True)
        with open(os.path.join(nul, "latest"), "w", encoding="utf-8") as fh:
            json.dump({"layers": None}, fh)
        idx = manifest_index(self.tmp)
        self.assertEqual(idx["sha256-ok"], {"good:1b"})

    def test_missing_root_is_empty_not_an_exception(self):
        self.assertEqual(manifest_index("/nonexistent/path/xyz"), {})


class TestBlobFromCmdline(unittest.TestCase):
    def test_space_separated_form(self):
        cmd = "/usr/local/bin/ollama runner --model /models/blobs/sha256-abc --port 1"
        self.assertEqual(blob_from_cmdline(cmd), "sha256-abc")

    def test_equals_form(self):
        self.assertEqual(blob_from_cmdline("ollama runner --model=/m/blobs/sha256-def"), "sha256-def")

    def test_a_non_runner_process_yields_None_not_a_guess(self):
        """ComfyUI on the same card must be left unnamed, not mislabelled."""
        self.assertIsNone(blob_from_cmdline("python3 /comfyui/main.py --listen"))
        self.assertIsNone(blob_from_cmdline(""))
        self.assertIsNone(blob_from_cmdline("ollama runner --model"))  # no value


class TestResolution(unittest.TestCase):
    IDX = {
        "sha256-shared": {"qwen2.5:7b", "vivid:latest", "weave:latest"},
        "sha256-solo": {"mistral:7b"},
    }

    def test_unique_blob_resolves_without_needing_the_resident_set(self):
        r = resolve_model_name("sha256-solo", self.IDX, resident=None)
        self.assertEqual(r["model"], "mistral:7b")
        self.assertTrue(r["exact"])

    def test_shared_blob_is_AMBIGUOUS_without_the_resident_set(self):
        r = resolve_model_name("sha256-shared", self.IDX, resident=None)
        self.assertIsNone(r["model"])
        self.assertFalse(r["exact"])
        self.assertEqual(len(r["candidates"]), 3)

    def test_resident_set_collapses_a_shared_blob_to_one_name(self):
        """The measured fix: blob alone said weave:latest; /api/ps says qwen2.5:7b."""
        r = resolve_model_name("sha256-shared", self.IDX, resident={"qwen2.5:7b", "mistral:7b"})
        self.assertEqual(r["model"], "qwen2.5:7b")
        self.assertTrue(r["exact"])

    def test_resident_set_that_still_leaves_two_stays_ambiguous(self):
        r = resolve_model_name("sha256-shared", self.IDX, resident={"vivid:latest", "weave:latest"})
        self.assertIsNone(r["model"])
        self.assertEqual(r["candidates"], ["vivid:latest", "weave:latest"])

    def test_empty_intersection_keeps_the_wider_candidates(self):
        """A racing load/unload must not erase a real blob's identity."""
        r = resolve_model_name("sha256-shared", self.IDX, resident={"llama3.2:3b"})
        self.assertEqual(len(r["candidates"]), 3)
        self.assertFalse(r["exact"])

    def test_unknown_or_missing_blob(self):
        for blob in (None, "", "sha256-nothere"):
            r = resolve_model_name(blob, self.IDX, resident={"mistral:7b"})
            self.assertIsNone(r["model"])
            self.assertEqual(r["candidates"], [])
            self.assertFalse(r["exact"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
