"""Regression test: the sandbox deploy gate must FAIL CLOSED when it cannot
apply the proposal's code_changes to the staging worktree.

Bug (found investigating #4930): `_sandbox_gate` wrote each change to
`/mnt/archie_sandbox/platform_v2/<file>` inside a try/except that only LOGGED a
warning on failure, then unconditionally restarted archie_staging and ran the
QA suite. If the worktree wasn't mounted into archie_platform (it wasn't) or any
single write failed, the gate validated STALE staging code and could FALSE-PASS
a production deploy of a fix that was never actually applied.

HoloDeck-P0 (2026-07-18): `code_changes` is now a unified-diff STRING (Task 1
made fix-gen emit repo-relative git-appliable diffs). `_apply_fix_to_sandbox`
base-syncs each touched file from live prod (so `git apply --check` measures
real drift), then `git apply --check` (FAIL CLOSED on drift/unapplicable) then
`git apply` for real into the `/mnt/archie_sandbox` worktree ROOT. `_sandbox_gate`
reverts the applied files in a `finally` so staging always comes back clean.
"""

import os
import subprocess

import services.proposal_service as ps

_DIFF = (
    "--- a/platform_v2/tools/brainstorm/__init__.py\n"
    "+++ b/platform_v2/tools/brainstorm/__init__.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
)


def _assert_git_calls_use_safe_directory(calls):
    """Every captured `git` invocation must set `-c safe.directory=*` — the
    sandbox worktree is root-owned but git in this container runs as a
    different uid, so a bare `git -C <path> ...` aborts with "detected
    dubious ownership" (rc=128). See KB fix: proposal_service._git()."""
    git_calls = [c for c in calls if c and c[0] == "git"]
    assert git_calls, "expected at least one captured git invocation"
    for c in git_calls:
        pairs = list(zip(c, c[1:]))
        assert (
            "-c" in c and "safe.directory=*" in c and ("-c", "safe.directory=*") in pairs
        ), f"git call missing '-c safe.directory=*': {c}"


def test_apply_fails_closed_when_worktree_not_mounted(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", _DIFF)
    assert res["error"] is not None
    assert "mount" in res["error"].lower()
    assert res["applied"] == []


def test_apply_rejects_non_string_changes(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", [{"file_path": "x", "content": "y"}])
    assert res["error"] is not None


def test_apply_rejects_diff_with_no_targets(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", "not a diff, no +++ lines")
    assert res["error"] is not None
    assert res["expected"] == 0


def test_apply_rejects_out_of_worktree_target(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    diff = "--- a/standalone_x/app.py\n+++ b/standalone_x/app.py\n@@ -1 +1 @@\n-a\n+b\n"
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", diff)
    assert res["error"] is not None
    assert "worktree" in res["error"].lower()


def test_apply_fails_closed_on_git_apply_check_drift(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    # base-sync resolves + copies fine ...
    monkeypatch.setattr(ps, "_basesync_touched", lambda root, touched: None)

    # ... but git apply --check reports the diff no longer applies (drift)
    def _run(cmd, **k):
        if "--check" in cmd:
            return subprocess.CompletedProcess(cmd, 1, b"", b"patch does not apply")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _run)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", _DIFF)
    assert res["error"] is not None
    assert "apply" in res["error"].lower()
    assert res["applied"] == []


def test_apply_happy_path_returns_touched(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(ps, "_basesync_touched", lambda root, touched: None)

    calls = []

    def _run(cmd, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _run)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", _DIFF)
    assert res["error"] is None
    assert res["applied"] == ["platform_v2/tools/brainstorm/__init__.py"]
    _assert_git_calls_use_safe_directory(calls)


def test_apply_reverts_worktree_on_partial_basesync_failure(monkeypatch):
    """A multi-file base-sync that fails partway (e.g. resolve_proposal_source
    can't resolve a later target) must not leave earlier-copied files dirty in
    the worktree — the failure branch must revert the full touched set."""
    monkeypatch.setattr(os.path, "isdir", lambda p: True)

    def _raise_basesync(root, touched):
        raise RuntimeError("cannot resolve prod source for platform_v2/b.py")

    monkeypatch.setattr(ps, "_basesync_touched", _raise_basesync)

    calls = []

    def _run(cmd, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _run)

    two_file_diff = (
        "--- a/platform_v2/a.py\n"
        "+++ b/platform_v2/a.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
        "--- a/platform_v2/b.py\n"
        "+++ b/platform_v2/b.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-y = 1\n"
        "+y = 2\n"
    )

    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", two_file_diff)
    assert res["error"] is not None
    assert "base-sync failed" in res["error"]

    revert_calls = [c for c in calls if "checkout" in c]
    assert revert_calls, "expected a git checkout revert call after base-sync failure"
    revert_call = revert_calls[0]
    assert "platform_v2/a.py" in revert_call
    assert "platform_v2/b.py" in revert_call
    _assert_git_calls_use_safe_directory(calls)


def test_sandbox_gate_bails_before_qa_when_apply_fails(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: False)  # worktree "not mounted"
    import services.qa_service as qs

    qa_called = {"v": False}
    monkeypatch.setattr(
        qs, "run_suite", lambda *a, **k: qa_called.__setitem__("v", True) or {"passed": 1, "total": 1, "run_id": 9}
    )
    out = ps._sandbox_gate(1, {"id": 1, "code_changes": _DIFF})
    assert out["passed"] is False
    assert qa_called["v"] is False, "gate ran QA against stale code — not fail-closed"
    assert out.get("error")
