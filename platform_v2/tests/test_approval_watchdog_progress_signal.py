"""The approval-queue watchdog must distinguish a WEDGED executor from a BUSY one.

Wait-age alone cannot make that distinction. A single legitimately slow action holds the
`max_instances=1` 'Approval Queue' slot, leaves approved rows waiting, and tripped the alarm
every single time — and the alert's own remedy text said "restart archie_scheduler to clear",
which fired mid-deploy destroys in-flight work.

Measured live 2026-08-15 (the incident these tests replay):
    13:16:01  archie_scheduler restarted
    13:17:13  backup_before_deploy #10557 executed (~70s)
    13:17 -> 13:33  website_deploy #10558 running — SIXTEEN MINUTES
    13:33:13  completes; queue then drains 10 items in ~3 min at ~20s each

Throughout that window the executor was healthy, yet the watchdog paged "likely wedged" and a
previous session followed its advice and restarted the scheduler. Two separate sessions read
the resulting "maximum number of running instances reached (1)" skip-spam as a hang.

The fix requires BOTH conditions before paging:
  1. approved rows waiting  > stale_min     (10 min)
  2. nothing completed for  > progress_min  (30 min)

These tests pin BOTH the silence (condition 2 unmet) and the firing (condition 2 met). A test
that only pinned silence would pass on a watchdog that never alerts at all.
"""

import sys
import types


sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

import agent_loop  # noqa: E402


class _FakeCursor:
    """Returns scripted rows in the order the watchdog issues its three queries:
    settings (fetchall) -> stalled rows (fetchall) -> progress age (fetchone)."""

    def __init__(self, settings, stalled, progress_age_min):
        self._settings = settings
        self._stalled = stalled
        self._progress = {"progress_age_min": progress_age_min}
        self._calls = 0

    def execute(self, *_a, **_k):
        self._calls += 1

    def fetchall(self):
        return self._settings if self._calls == 1 else self._stalled

    def fetchone(self):
        return self._progress

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *_a, **_k):
        return self._cursor

    def close(self):
        pass


def _run_watchdog(monkeypatch, *, stalled, progress_age_min, settings=None):
    """Drive the watchdog against scripted DB state; return the send_system calls it made."""
    cur = _FakeCursor(settings or [], stalled, progress_age_min)
    monkeypatch.setattr(agent_loop, "get_db", lambda: _FakeConn(cur))

    sent = []
    fake_mod = types.ModuleType("services.telegram_service")
    fake_mod.send_system = lambda title, body, source=None: sent.append(
        {"title": title, "body": body, "source": source}
    )
    monkeypatch.setitem(sys.modules, "services.telegram_service", fake_mod)

    stub = types.SimpleNamespace(
        _APPROVAL_WATCHDOG_STALE_MIN=agent_loop.AgentLoop._APPROVAL_WATCHDOG_STALE_MIN,
        _APPROVAL_WATCHDOG_PROGRESS_MIN=agent_loop.AgentLoop._APPROVAL_WATCHDOG_PROGRESS_MIN,
    )
    agent_loop.AgentLoop._approval_queue_watchdog(stub)
    return sent


_WAITING = [
    {"id": 10802, "action_type": "linkedin_post", "approved_at": "2026-08-15T13:05:00Z"},
    {"id": 10806, "action_type": "pr_merge", "approved_at": "2026-08-15T13:14:00Z"},
]


def test_busy_executor_does_not_page(monkeypatch):
    """THE REGRESSION. Rows waiting past stale_min, but an item completed 5 min ago.

    This is the 2026-08-15 website_deploy shape. The old wait-age-only watchdog paged here.
    """
    sent = _run_watchdog(monkeypatch, stalled=_WAITING, progress_age_min=5.0)
    assert sent == [], f"paged while the executor was actively draining: {sent}"


def test_busy_just_under_threshold_does_not_page(monkeypatch):
    """Boundary: 29 min of no completions is still under the 30 min threshold."""
    sent = _run_watchdog(monkeypatch, stalled=_WAITING, progress_age_min=29.0)
    assert sent == [], "paged below progress_min — the threshold is not being honoured"


def test_genuine_wedge_still_pages(monkeypatch):
    """The alarm must NOT have been disabled: no progress for 45 min WITH rows waiting."""
    sent = _run_watchdog(monkeypatch, stalled=_WAITING, progress_age_min=45.0)
    assert len(sent) == 1, "a real wedge no longer alerts — the watchdog is now useless"
    assert "45" in sent[0]["body"], "alert omits how long progress has been stalled"


def test_never_executed_with_rows_waiting_pages(monkeypatch):
    """NULL progress (nothing ever executed) plus waiting rows is a genuine stall."""
    sent = _run_watchdog(monkeypatch, stalled=_WAITING, progress_age_min=None)
    assert len(sent) == 1
    assert "EVER" in sent[0]["body"]


def test_empty_queue_never_pages(monkeypatch):
    """A fresh install has no approved rows and must not page even with no progress ever."""
    sent = _run_watchdog(monkeypatch, stalled=[], progress_age_min=None)
    assert sent == []


def test_alert_does_not_recommend_blind_restart(monkeypatch):
    """The old remedy text ordered a scheduler restart, which mid-deploy destroys work."""
    sent = _run_watchdog(monkeypatch, stalled=_WAITING, progress_age_min=45.0)
    body = sent[0]["body"]
    assert "restart archie_scheduler to clear" not in body
    assert "DIAGNOSE BEFORE RESTARTING" in body


def test_progress_threshold_exceeds_slowest_measured_action():
    """website_deploy measured 16 min. progress_min must stay clear of it, or the false
    positive returns for every deploy."""
    assert agent_loop.AgentLoop._APPROVAL_WATCHDOG_PROGRESS_MIN >= 20
