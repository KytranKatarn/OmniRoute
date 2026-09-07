"""Regression tests for the admission gates' bridge_jobs counting WINDOW.

THE BUG THESE PIN (2026-09-07 hub outage, 23:00 UTC — 47 attempts, 0 successes):

``hub_lane_over_cap`` and ``in_flight_over_cap`` both count in-flight work as
``bridge_jobs`` rows with ``created_at > NOW() - window_minutes``. That window was
10 minutes. #5925 had raised ``fact_check``'s deadline 300s -> 600s, which is
EXACTLY 10 minutes — so a job sitting on its deadline aged out of the very count
that was supposed to be bounding it, while it still occupied the hub slot.

Measured during the incident: fact_check p90 lifetime 600.0s; 44 of 147
contended-lane jobs outlived the window; in-flight peaked at 31 against a
nominal cap of 8.

It presents as a cliff rather than a slope because it is a POSITIVE FEEDBACK
LOOP — saturation lengthens jobs, longer jobs age out of the count, the
undercount admits more work, which deepens saturation.

The load-bearing test here is ``test_gate_window_exceeds_longest_dispatch_deadline``:
it reads the REAL ``CAPABILITY_TIMEOUTS`` from the dispatcher, so a future
deadline raise turns this file RED instead of silently re-breaking the gate.
That cross-module check lives in a test rather than at runtime on purpose —
``department_dispatcher`` imports this service, so importing it back at module
scope would be circular.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_admission_gate_window.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import welfare_governance_service as wgs  # noqa: E402


def _longest_dispatch_deadline_s():
    """Max CAPABILITY_TIMEOUTS value from the dispatcher, or skip if unimportable.

    SKIP (not pass) on ImportError: a test that silently succeeds when it cannot
    reach its subject is the "unmonitored while appearing monitored" shape this
    codebase keeps getting bitten by.
    """
    try:
        from tools.department_hq.services.department_dispatcher import CAPABILITY_TIMEOUTS
    except Exception as exc:  # pragma: no cover - import environment dependent
        pytest.skip(f"dispatcher not importable here: {exc}")
    assert CAPABILITY_TIMEOUTS, "CAPABILITY_TIMEOUTS is empty — cannot verify the invariant"
    return max(CAPABILITY_TIMEOUTS.values())


# ── the invariant ────────────────────────────────────────────────────────────


def test_gate_window_exceeds_longest_dispatch_deadline():
    """THE invariant. Window must be STRICTLY greater than the longest deadline.

    Equality is the bug: at window == deadline a job on its deadline is on the
    boundary and drops out of its own denominator. This asserts strict '>' so
    that re-introducing the 600s/10min alias fails here.
    """
    longest_s = _longest_dispatch_deadline_s()
    window_s = wgs.GATE_WINDOW_MINUTES * 60
    assert window_s > longest_s, (
        f"admission-gate window {window_s}s must EXCEED the longest dispatch "
        f"deadline {longest_s}s — otherwise a job still holding a slot ages out "
        f"of the count that exists to bound it (2026-09-07 hub outage). "
        f"Raise welfare_governance_service.GATE_WINDOW_MINUTES."
    )


def test_gate_window_keeps_a_finite_zombie_bound():
    """The window must stay FINITE — it is what stops a stuck job gating forever.

    Guards the opposite over-correction: 'just make the window huge'. Upper bound
    is generous (1h); the point is that an unbounded window is not acceptable.
    """
    assert 0 < wgs.GATE_WINDOW_MINUTES <= 60, (
        "GATE_WINDOW_MINUTES must stay a bounded, positive number of minutes so a "
        "stuck zombie job can never permanently gate its lane."
    )


# ── both gates must actually USE it ──────────────────────────────────────────


class _FakeCtx:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *a):
        return False


class _WindowCapturingCur:
    """Captures the params handed to the bridge_jobs COUNT query."""

    def __init__(self, count=0):
        self._count = count
        self._last = None
        self.count_params = None

    def execute(self, sql, params=None):
        self._last = (sql, params)
        if "bridge_jobs" in sql:
            self.count_params = params

    def fetchone(self):
        sql = self._last[0]
        if "platform_settings" in sql:
            return None  # → function falls back to its default cap
        return {"n": self._count}


def _patch(monkeypatch, cur):
    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _FakeCtx(cur))


def test_hub_lane_gate_counts_over_the_full_window(monkeypatch):
    cur = _WindowCapturingCur(count=0)
    _patch(monkeypatch, cur)
    wgs.hub_lane_over_cap()
    assert cur.count_params is not None, "bridge_jobs COUNT was never executed"
    assert wgs.GATE_WINDOW_MINUTES in cur.count_params, (
        f"hub_lane_over_cap must count over GATE_WINDOW_MINUTES "
        f"({wgs.GATE_WINDOW_MINUTES}); got params {cur.count_params}"
    )


def test_per_job_type_gate_counts_over_the_full_window(monkeypatch):
    """in_flight_over_cap is the gate the WTF analyze path actually calls
    (tools/wtf_hub/routes.py), so it carries the same aliasing risk."""
    cur = _WindowCapturingCur(count=0)
    _patch(monkeypatch, cur)
    wgs.in_flight_over_cap("fact_check")
    assert cur.count_params is not None, "bridge_jobs COUNT was never executed"
    assert wgs.GATE_WINDOW_MINUTES in cur.count_params, (
        f"in_flight_over_cap must count over GATE_WINDOW_MINUTES "
        f"({wgs.GATE_WINDOW_MINUTES}); got params {cur.count_params}"
    )


def test_both_gates_share_one_window():
    """One constant, so a future fix cannot correct one gate and miss the other —
    the per-caller-guard shape (#5194/#5862/#6035) this fleet keeps repeating."""
    import inspect

    hub_default = inspect.signature(wgs.hub_lane_over_cap).parameters["window_minutes"].default
    job_default = inspect.signature(wgs.in_flight_over_cap).parameters["window_minutes"].default
    assert hub_default == job_default == wgs.GATE_WINDOW_MINUTES


# ── the gate still gates ─────────────────────────────────────────────────────


def test_gate_fires_when_in_flight_reaches_cap(monkeypatch):
    """Widening the window must not disturb the actual admission decision."""
    _patch(monkeypatch, _WindowCapturingCur(count=8))
    assert wgs.hub_lane_over_cap(default_cap=8) is True


def test_gate_open_below_cap(monkeypatch):
    _patch(monkeypatch, _WindowCapturingCur(count=7))
    assert wgs.hub_lane_over_cap(default_cap=8) is False
