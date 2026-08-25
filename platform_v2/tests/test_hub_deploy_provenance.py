"""Regression: a merge must never be reported as deployed when it isn't (#5375).

2026-07-28: PR #2543 merged, both containers restarted, and the platform still
ran the PRE-merge code — ``/app`` is bind-mounted from a checkout that was two
commits behind ``origin/main``. GitHub said merged, Repair Bay said approved,
the restart exited 0. Nothing measured the running code, so nothing objected.

The properties pinned here:

* the checkout being behind ⇒ ``pull_required`` (a restart would deploy nothing)
* code newer than the process ⇒ ``restart_required`` (on disk, not loaded)
* **an UNKNOWN is never reported as live** — this is the one that matters. The
  original bug was a green status over a broken reality; a provenance checker
  that resolves its own ignorance to "fine" reproduces exactly that.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import hub_deploy_provenance as hdp  # noqa: E402

SHA_A = "aa655ee89ffffffffffffffffffffffffffffff1"
SHA_B = "bb00000000ffffffffffffffffffffffffffffff"


@pytest.fixture
def stub(monkeypatch):
    """Drive check_hub_deploy() through its four outcomes deterministically."""

    def _apply(local, remote, newest_mtime=None, proc_start=None):
        monkeypatch.setattr(hdp, "local_head", lambda *a, **k: local)
        monkeypatch.setattr(hdp, "remote_head", lambda *a, **k: remote)
        monkeypatch.setattr(
            hdp, "newest_source_mtime", lambda *a, **k: (None if newest_mtime is None else (newest_mtime, "/app/x.py"))
        )
        monkeypatch.setattr(hdp, "_proc_start_time", lambda *a, **k: proc_start)

    return _apply


def test_checkout_behind_origin_is_pull_required(stub):
    """The exact 2026-07-28 failure: merged on GitHub, absent from the checkout."""
    stub(local=SHA_A, remote=SHA_B)
    result = hdp.check_hub_deploy()
    assert result["status"] == hdp.STATUS_PULL_REQUIRED
    assert not hdp.is_live(result)
    # The operator must be told restarting is futile here, not just "drift".
    assert "not on disk" in result["reason"]


def test_code_newer_than_process_is_restart_required(stub):
    """Pulled but not reloaded — the inspect.getsource trap."""
    stub(local=SHA_A, remote=SHA_A, newest_mtime=5000.0, proc_start=1000.0)
    result = hdp.check_hub_deploy()
    assert result["status"] == hdp.STATUS_RESTART_REQUIRED
    assert not hdp.is_live(result)


def test_matching_head_and_older_source_is_in_sync(stub):
    stub(local=SHA_A, remote=SHA_A, newest_mtime=1000.0, proc_start=5000.0)
    result = hdp.check_hub_deploy()
    assert result["status"] == hdp.STATUS_IN_SYNC
    assert hdp.is_live(result)


@pytest.mark.parametrize(
    "local,remote",
    [(None, SHA_A), (SHA_A, None), (None, None)],
)
def test_unknown_is_fail_open_never_drift_and_never_live(stub, local, remote):
    """UNKNOWN must be neither an alarm nor an all-clear.

    Alarming on our own outage gets the monitor muted; reporting it as in_sync
    recreates the green-status-over-broken-reality bug this module exists for.
    """
    stub(local=local, remote=remote)
    result = hdp.check_hub_deploy()
    assert result["status"] == hdp.STATUS_FAIL_OPEN
    assert result["status"] != hdp.STATUS_PULL_REQUIRED
    assert not hdp.is_live(result)


def test_unreadable_proc_does_not_claim_in_sync(stub):
    """Heads match but the process start is unknown — still not provably live."""
    stub(local=SHA_A, remote=SHA_A, newest_mtime=1000.0, proc_start=None)
    result = hdp.check_hub_deploy()
    assert result["status"] == hdp.STATUS_FAIL_OPEN
    assert not hdp.is_live(result)


def test_check_never_raises(monkeypatch):
    """A monitor that can crash is a monitor that silently stops monitoring."""

    def boom(*a, **k):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(hdp, "local_head", boom)
    result = hdp.check_hub_deploy()
    assert result["status"] == hdp.STATUS_FAIL_OPEN
    assert not hdp.is_live(result)


def test_describe_gives_the_operator_the_remedy(stub):
    """The Telegram reply must carry the fix, not just a complaint."""
    stub(local=SHA_A, remote=SHA_B)
    text = hdp.describe(hdp.check_hub_deploy())
    assert "NOT DEPLOYED" in text
    assert "merge --ff-only origin/main" in text
    # Never a destructive suggestion: that tree holds uncommitted work.
    assert "reset --hard" not in text


def test_describe_handles_garbage_without_claiming_success():
    for bad in (None, {}, {"status": "nonsense"}):
        assert "UNKNOWN" in hdp.describe(bad)
        assert not hdp.is_live(bad)


def _make_git_dir(root, head_content, refs=None, packed=None):
    git_dir = os.path.join(root, ".git")
    os.makedirs(os.path.join(git_dir, "refs", "heads"), exist_ok=True)
    with open(os.path.join(git_dir, "HEAD"), "w", encoding="utf-8") as fh:
        fh.write(head_content)
    for ref_path, sha in (refs or {}).items():
        full = os.path.join(git_dir, ref_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(sha + "\n")
    if packed is not None:
        with open(os.path.join(git_dir, "packed-refs"), "w", encoding="utf-8") as fh:
            fh.write(packed)
    return root


def test_head_read_from_loose_ref(tmp_path):
    """The real reader — no git binary, so container ownership rules can't veto it."""
    root = _make_git_dir(str(tmp_path), "ref: refs/heads/main\n", refs={"refs/heads/main": SHA_A})
    assert hdp.head_from_git_dir(root) == SHA_A


def test_head_read_from_packed_refs(tmp_path):
    """A freshly cloned/gc'd repo has no loose ref — packed-refs must still resolve."""
    root = _make_git_dir(
        str(tmp_path),
        "ref: refs/heads/main\n",
        packed=f"# pack-refs with: peeled fully-peeled sorted\n{SHA_A} refs/heads/main\n",
    )
    assert hdp.head_from_git_dir(root) == SHA_A


def test_head_read_detached(tmp_path):
    root = _make_git_dir(str(tmp_path), SHA_B + "\n")
    assert hdp.head_from_git_dir(root) == SHA_B


def test_head_read_missing_repo_returns_none_not_garbage(tmp_path):
    assert hdp.head_from_git_dir(str(tmp_path / "nope")) is None


def test_head_reader_works_against_this_actual_repository():
    """Live check against the real checkout this test runs from.

    Guards the regression directly: if the reader ever silently returns None
    here, check_hub_deploy() degrades to permanent fail_open and the monitor
    goes quiet without ever failing.
    """
    # os.path flavour of the #5994 bug: /app/tests/../.. is "/" in the container, so the
    # assertion below reported "could not read HEAD from /" — a real-looking monitor
    # failure caused entirely by the path.
    from tests.repo_root import repo_root as _rr

    repo_root = str(_rr())
    sha = hdp.head_from_git_dir(repo_root)
    assert sha, f"could not read HEAD from {repo_root} — monitor would be permanently blind"
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), sha


def test_monitor_job_is_registered_on_wall_clock():
    """Same lesson as #5007: an uptime-relative observer goes blind after a restart."""
    from apscheduler.triggers.cron import CronTrigger

    from services.fleet_jobs import register_fleet_jobs

    jobs = {}

    class _Stub:
        def add_job(self, func=None, trigger=None, id=None, **kw):  # noqa: A002
            jobs[id] = trigger

    register_fleet_jobs(_Stub(), flask_app=None)
    assert "hub_deploy_provenance" in jobs, "the observer is not scheduled at all"
    trigger = jobs["hub_deploy_provenance"]
    assert isinstance(trigger, CronTrigger), f"got {type(trigger).__name__}, not wall-clock"
    assert getattr(trigger, "timezone", None) is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
