"""#5383 / #5386(a) — a M.A.V.E.N. probe must not report work it did not do.

`download_pipeline_probe` fired `DownloadedMoviesScan`, threw the response away,
and appended "triggered ..." unconditionally. It therefore reported that it had
healed the pipeline every 30 minutes for 20 days while the command failed
instantly each time. `library_coverage_probe` had the same shape three more
times, plus a branch that fired a scan and appended an action but never an
issue — so `if not issues: return` skipped both the self-heal log and the
A.R.C.H.I.E. notify, making the work invisible even when it happened.

A self-heal that cannot fail is not a self-heal.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from tests.repo_root import repo_root

_HO_PATH = repo_root() / "standalone" / "media_hub" / "health_observer.py"

# The standalone tree is NOT mounted in archie_platform (only platform_v2 -> /app), so
# parents[2] resolves to "/standalone/..." here and the file is absent. Skip honestly:
# a FileNotFoundError at import time aborts collection for the ENTIRE suite (#5665).
if not _HO_PATH.exists():  # pragma: no cover - environment-dependent
    pytest.skip(
        f"media_hub standalone tree not available at {_HO_PATH} (not mounted in this container)",
        allow_module_level=True,
    )


def _load():
    spec = importlib.util.spec_from_file_location("_mh_health_observer", _HO_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_mh_health_observer"] = mod
    spec.loader.exec_module(mod)
    return mod


ho = _load()


class _Resp:
    def __init__(self, ok=True, status_code=200, payload=None, text=""):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# _arr_command — the POST itself
# ---------------------------------------------------------------------------


def test_rejected_post_is_a_failure(monkeypatch):
    """A 400 must NOT read as a triggered scan — this is the #5383 bug."""
    monkeypatch.setattr(ho.requests, "post", lambda *a, **k: _Resp(ok=False, status_code=400, text="Path is required"))

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "DownloadedMoviesScan"})

    assert ok is False
    assert "400" in detail
    assert "Path is required" in detail, "the *arr reason must be surfaced, not swallowed"


def test_network_error_is_a_failure(monkeypatch):
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(ho.requests, "post", _boom)

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "X"})

    assert ok is False
    assert "connection refused" in detail


# ---------------------------------------------------------------------------
# _arr_command — the command OUTCOME (accepted != succeeded)
# ---------------------------------------------------------------------------


def test_command_that_fails_after_acceptance_is_a_failure(monkeypatch):
    """*arr accepts, queues, THEN fails. The 201 alone proves nothing."""
    monkeypatch.setattr(ho.requests, "post", lambda *a, **k: _Resp(payload={"id": 42}))
    monkeypatch.setattr(
        ho.requests,
        "get",
        lambda *a, **k: _Resp(payload={"status": "failed", "exception": "folder does not exist"}),
    )
    monkeypatch.setattr(ho._time, "sleep", lambda *_: None)

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "X"})

    assert ok is False
    assert "folder does not exist" in detail


def test_completed_command_succeeds(monkeypatch):
    monkeypatch.setattr(ho.requests, "post", lambda *a, **k: _Resp(payload={"id": 7}))
    monkeypatch.setattr(ho.requests, "get", lambda *a, **k: _Resp(payload={"status": "completed"}))
    monkeypatch.setattr(ho._time, "sleep", lambda *_: None)

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "X"})

    assert ok is True
    assert "completed" in detail


def test_unverifiable_outcomes_say_so(monkeypatch):
    """Accepted-but-unconfirmed must be labelled, never reported as done."""
    monkeypatch.setattr(ho.requests, "post", lambda *a, **k: _Resp(payload={}))  # no id

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "X"})

    assert ok is True
    assert "unverified" in detail


def test_still_running_at_deadline_is_labelled_unverified(monkeypatch):
    monkeypatch.setattr(ho.requests, "post", lambda *a, **k: _Resp(payload={"id": 9}))
    monkeypatch.setattr(ho.requests, "get", lambda *a, **k: _Resp(payload={"status": "started"}))
    monkeypatch.setattr(ho._time, "sleep", lambda *_: None)

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "X"}, verify_seconds=0.01)

    assert ok is True
    assert "unverified" in detail


def test_status_check_failure_does_not_claim_completion(monkeypatch):
    monkeypatch.setattr(ho.requests, "post", lambda *a, **k: _Resp(payload={"id": 5}))

    def _boom(*a, **k):
        raise OSError("timeout")

    monkeypatch.setattr(ho.requests, "get", _boom)
    monkeypatch.setattr(ho._time, "sleep", lambda *_: None)

    ok, detail = ho._arr_command("http://x/api/v3", {"name": "X"})

    assert ok is True, "the command WAS accepted"
    assert "unverified" in detail, "but the outcome is unknown and must say so"


# ---------------------------------------------------------------------------
# Source invariants — the defect must not creep back in
# ---------------------------------------------------------------------------


def test_no_probe_posts_a_command_directly():
    """Every *arr command must go through _arr_command.

    A direct `requests.post(f"{base}/command"...)` is the exact shape that
    discards the outcome; if one reappears the phantom-success bug is back.
    """
    src = _HO_PATH.read_text()
    body = src.split("def _arr_command", 1)[1]
    # Skip _arr_command's own implementation, check everything after it.
    after = body.split("\ndef ", 1)[1]

    assert 'f"{base}/command"' not in after, "a probe is posting a command directly again"
    assert 'f"{base}/command?apikey=' not in after, "a probe is posting a command directly again"


def test_healthy_log_does_not_overclaim():
    """The 97x 'Sonarr coverage healthy' line described more than it measured."""
    src = _HO_PATH.read_text()

    # Match the full LOG LITERAL, not the bare phrase — the phrase also appears
    # in the comment explaining the bug, so a loose grep fails on correct code.
    # (Third time today a source-check matched its own documentation.)
    assert '"library_coverage_probe: Sonarr coverage healthy"' not in src, "restores a status that overclaims"
    assert "no series with 0 imported episodes" in src


def test_aged_gap_is_reported_but_not_auto_searched():
    """Visibility and action are separate decisions.

    Widening the auto-search window would auto-grab the aged backlog onto a disk
    with 1,736 uncorrectable sectors (#5385), against an explicit owner hold. The
    gap must be REPORTED without being ACTED on.
    """
    src = _HO_PATH.read_text()

    assert "NOT auto-searched" in src
    assert "totalRecords" in src, "the true count must come from totalRecords, not the capped page"
    assert "timedelta as _tdl" in src and "days=30" in src, "the 30-day ACTION window must remain"


def test_radarr_coverage_branch_records_an_issue():
    """It appended an action but no issue, so `if not issues: return` hid it."""
    src = _HO_PATH.read_text()
    radarr_block = src.split("# ---- Radarr: monitored movies without files ----", 1)[1]

    assert "monitored, available movie(s) have no file" in radarr_block
    idx_issue = radarr_block.index("issues.append")
    idx_cmd = radarr_block.index("_arr_command")
    assert idx_issue < idx_cmd, "the issue must be recorded even if the command then fails"


@pytest.mark.parametrize("probe", ["download_pipeline_probe", "library_coverage_probe"])
def test_probes_still_importable(probe):
    assert callable(getattr(ho, probe))
