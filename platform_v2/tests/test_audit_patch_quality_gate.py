"""Drive the real generation path: no invalid patch or model-only closure."""

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import services.audit_pipeline as pipeline
import services.work_tracking_service as tracking


@pytest.fixture
def generation(monkeypatch, tmp_path):
    source = tmp_path / "source.py"
    response = SimpleNamespace(success=True, response="", agent_name="fixture")
    meta = {
        "source": "code_health_audit",
        "file_path": "platform_v2/tools/fixture/source.py",
        "issue_code": "PYFLAKES",
        "detail": "local variable 'unused' is assigned to but never used",
        "module_name": "fixture",
    }
    updates = []
    archived = []
    failures = []

    class Cursor:
        def execute(self, sql, params=None):
            self.sql = sql
            if "UPDATE improvement_proposals" in sql:
                updates.append((sql, params))

        def fetchone(self):
            if "SELECT id FROM agents" in self.sql:
                return None
            return {"id": 1, "title": "fixture", "description": "fixture", "metadata": meta, "status": "approved"}

    @contextmanager
    def db(*args, **kwargs):
        yield None, Cursor()

    monkeypatch.setattr(pipeline, "get_db_cursor", db)
    monkeypatch.setattr(pipeline, "resolve_proposal_source", lambda path: (str(source), meta["file_path"], "ok"))
    monkeypatch.setattr(pipeline, "_ensure_import_paths", lambda: None)
    monkeypatch.setattr(pipeline, "creed_gate_pre_dispatch", lambda pid: {"approved": True})
    monkeypatch.setattr(tracking, "create_work_session", lambda **kw: None)
    monkeypatch.setattr(pipeline, "_archive_stale_proposal", lambda pid, **kw: archived.append((pid, kw)))
    monkeypatch.setattr(pipeline, "_capture_fix_failure", lambda pid, raw, reason: failures.append(reason))
    monkeypatch.setitem(
        sys.modules,
        "tools.department_hq.services.department_dispatcher",
        SimpleNamespace(get_dispatcher=lambda: SimpleNamespace(request_work=lambda **kw: response)),
    )

    def run(original, replacement=None, nofix=False):
        source.write_text(original)
        response.response = "<<<NOFIX>>>" if nofix else json.dumps({"find": original, "replace": replacement})
        return pipeline.dispatch_proposal_fix(1)

    return run, meta, updates, archived, failures


ORIGINAL = "def example():\n    unused = 1\n    return 2\n"
FIXED = "def example():\n    return 2\n"


def test_invalid_python_never_reaches_ready_for_review(generation):
    run, _, updates, archived, failures = generation
    result = run(ORIGINAL, "def example():\n    // unused = 1\n    return 2\n")
    assert result["error"] == "fix_apply:invalid_python"
    assert updates == archived == [] and failures == ["invalid_python"]


def test_syntactically_valid_nonfix_is_rejected(generation):
    run, _, updates, _, failures = generation
    result = run(ORIGINAL, ORIGINAL.replace("unused = 1", "unused = 2"))
    assert result["error"] == "fix_apply:finding_still_present"
    assert updates == [] and failures == ["finding_still_present"]


def test_verified_fix_can_reach_review(generation):
    run, _, updates, archived, failures = generation
    result = run(ORIGINAL, FIXED)
    assert result["success"] is True
    assert len(updates) == 1 and "ready_for_review" in updates[0][0]
    assert archived == failures == []


@pytest.mark.parametrize("unknown", [False, True])
def test_model_nofix_cannot_close_present_or_unknown_findings(generation, unknown):
    run, meta, updates, archived, failures = generation
    if unknown:
        meta["issue_code"] = "UNKNOWN"
        meta["detail"] = "requires manual inspection"
    result = run(ORIGINAL, nofix=True)
    assert result["error"] == "nofix:unverified"
    assert updates == archived == [] and failures == ["nofix_unverified"]


def test_model_nofix_can_close_only_a_disproved_finding(generation):
    run, _, updates, archived, failures = generation
    result = run(FIXED, nofix=True)
    assert result["stale"] is True
    assert archived[0][1]["archive_reason"] == "stale:finding_resolved"
    assert updates == failures == []


def test_diff_generation_failure_never_stores_a_placeholder(generation, monkeypatch):
    run, _, updates, _, failures = generation

    def broken(*args):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(pipeline, "_build_fix_diff", broken)
    result = run(ORIGINAL, FIXED)
    assert result["error"] == "fix_apply:diff_generation_failed"
    assert updates == [] and failures == ["diff_generation_failed"]
