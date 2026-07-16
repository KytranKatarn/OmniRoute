"""Regression test: the sandbox deploy gate must FAIL CLOSED when it cannot
apply the proposal's code_changes to the staging worktree.

Bug (found investigating #4930): `_sandbox_gate` wrote each change to
`/mnt/archie_sandbox/platform_v2/<file>` inside a try/except that only LOGGED a
warning on failure, then unconditionally restarted archie_staging and ran the
QA suite. If the worktree wasn't mounted into archie_platform (it wasn't) or any
single write failed, the gate validated STALE staging code and could FALSE-PASS
a production deploy of a fix that was never actually applied.

The fix extracts the apply step into `_apply_fix_to_sandbox()` and makes
`_sandbox_gate` return passed=False (never reaching the QA run) whenever the fix
could not be fully applied. The gate stays fail-closed: no valid apply -> no
validation -> no deploy.
"""

import os

import services.proposal_service as ps


# ── the extracted, independently-testable apply helper ───────────────────────
def test_apply_fails_closed_when_worktree_not_mounted(monkeypatch):
    # archie_platform without the /mnt/archie_sandbox mount -> path is not a dir
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox/platform_v2", [{"file_path": "x.py", "content": "y"}])
    assert res["error"] is not None
    assert "mount" in res["error"].lower()
    assert res["applied"] == []


def test_apply_fails_closed_on_write_error(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    def _boom(*a, **k):
        raise OSError("read-only fs")

    monkeypatch.setattr("builtins.open", _boom)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox/platform_v2", [{"file_path": "x.py", "content": "y"}])
    assert res["error"] is not None
    assert "x.py" in res["error"]


def test_apply_rejects_unparseable_changes(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    res = ps._apply_fix_to_sandbox("/sb", "{not valid json")
    assert res["error"] is not None


def test_apply_rejects_empty_changes(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    res = ps._apply_fix_to_sandbox("/sb", [])
    assert res["error"] is not None


def test_apply_happy_path_writes_all(tmp_path):
    sb = str(tmp_path)
    res = ps._apply_fix_to_sandbox(sb, [{"file_path": "a/b.py", "content": "print(1)"}])
    assert res["error"] is None
    assert res["applied"] == ["a/b.py"]
    assert (tmp_path / "a" / "b.py").read_text() == "print(1)"


# ── the gate itself must bail before ever running QA on a failed apply ────────
def test_sandbox_gate_bails_before_qa_when_apply_fails(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: False)  # worktree "not mounted"

    import services.qa_service as qs

    qa_called = {"v": False}

    def _run_suite(*a, **k):
        qa_called["v"] = True
        return {"passed": 1, "total": 1, "run_id": 9}

    monkeypatch.setattr(qs, "run_suite", _run_suite)

    out = ps._sandbox_gate(1, {"id": 1, "code_changes": [{"file_path": "x.py", "content": "y"}]})
    assert out["passed"] is False
    assert qa_called["v"] is False, "gate ran QA against stale code — not fail-closed"
    assert out.get("error")
