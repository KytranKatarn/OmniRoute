"""modelfile_sync — registration must not depend on a writable /mnt/llm_drive (#6115).

Two independent defects made export_modelfile a silent no-op from archie_platform:
  1. the on-disk Modelfile write ran FIRST and returned on failure — and the
     platform container mounts /mnt/llm_drive/ollama/models read-only, so the
     Ollama registration (which needs no file at all) was never attempted; and
  2. the /api/create payload used the legacy {"name","modelfile"} schema, which
     modern Ollama (hub host runs 0.16.x) no longer accepts — so registration
     would have failed even with the file written.

These tests pin the fixed contract: register first with the modern structured
schema; the disk write is a best-effort audit copy that can never block.
"""

import io
import json
from unittest.mock import patch

from tools.department_hq.services import modelfile_sync as ms


def _ok_response(body=b'{"status":"success"}'):
    return io.BytesIO(body)


class TestModernCreateSchema:
    def test_payload_uses_model_from_system_not_legacy_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "MODELFILE_DIR", str(tmp_path))
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _ok_response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = ms.export_modelfile("V.I.V.I.D.", "qwen2.5:7b", "You are V.I.V.I.D.")

        assert res["success"] is True
        p = captured["payload"]
        assert p["model"] == "vivid"
        assert p["from"] == "qwen2.5:7b"
        assert p["system"] == "You are V.I.V.I.D."
        # the legacy fields modern Ollama rejects must be GONE
        assert "name" not in p and "modelfile" not in p

    def test_audit_copy_written_when_dir_is_writable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ms, "MODELFILE_DIR", str(tmp_path))
        with patch("urllib.request.urlopen", return_value=_ok_response()):
            res = ms.export_modelfile("W.E.A.V.E.", "qwen2.5:7b", "prompt")
        assert res["modelfile_path"] and (tmp_path / "Modelfile.weave").exists()


class TestReadOnlyMountNeverBlocks:
    def test_registration_succeeds_even_when_disk_write_fails(self, monkeypatch):
        """THE #6115 case: archie_platform's read-only mount. Registration is the
        functional step and must run and succeed regardless of the audit copy."""
        monkeypatch.setattr(ms, "MODELFILE_DIR", "/proc/definitely-not-writable/x")
        with patch("urllib.request.urlopen", return_value=_ok_response()) as u:
            res = ms.export_modelfile("V.I.V.I.D.", "qwen2.5:7b", "prompt")
        assert u.called, "registration must be ATTEMPTED before/despite any disk failure"
        assert res["success"] is True
        assert res["modelfile_path"] is None
        assert "audit copy not written" in res["message"]


class TestRegistrationFailureIsHonest:
    def test_transport_failure_returns_success_false(self, tmp_path, monkeypatch):
        """The OLD code returned success=True on API failure ('file was written').
        The file is not the product — a failed registration must say so."""
        monkeypatch.setattr(ms, "MODELFILE_DIR", str(tmp_path))
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            res = ms.export_modelfile("V.I.V.I.D.", "qwen2.5:7b", "prompt")
        assert res["success"] is False
        assert "registration failed" in res["message"].lower()

    def test_in_stream_error_with_http_200_is_a_failure(self, tmp_path, monkeypatch):
        """Ollama streams status lines and can deliver an error INSIDE a 200 body."""
        monkeypatch.setattr(ms, "MODELFILE_DIR", str(tmp_path))
        body = b'{"error":"model \'nope:1b\' not found"}'
        with patch("urllib.request.urlopen", return_value=_ok_response(body)):
            res = ms.export_modelfile("V.I.V.I.D.", "nope:1b", "prompt")
        assert res["success"] is False
        assert "not found" in res["message"]

    def test_empty_prompt_still_refused(self):
        assert ms.export_modelfile("X", "qwen2.5:7b", "  ")["success"] is False
