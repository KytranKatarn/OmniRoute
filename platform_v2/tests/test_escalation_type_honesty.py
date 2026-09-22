"""The misroute audit reported EVERY escalation as a floor fallback (2026-09-22).

MEASURED before the fix, 24h of production: 1,291 `Throughput: awaiting cloud approval`
+ ~54 `paid cloud approved`, and ZERO genuine floor fallbacks — yet the audit reported
"1,345 floor-fallback hits" against a threshold of 20, every single run.

TWO defects, and the second is the dangerous one:
  1. `_floor_fallback()` selected EVERY row of dispatch_escalation_log with no type
     filter, so it has always reported the cloud/throughput number under a floor-fallback
     name. A permanently-firing alarm is an alarm nobody reads.
  2. Genuine floor fallbacks were NEVER WRITTEN ANYWHERE. `orchestration_engine` step 6
     sets `source = "floor_fallback"` as a LOCAL VARIABLE and drops it; the table's only
     writer was the cloud path. So floor fallbacks were unmonitored while APPEARING
     monitored — the phantom-`backups`-table shape.

⚠️ The throughput volume must stay VISIBLE, not be silenced. Renaming the metric must not
turn 1,291 real escalations into nothing; `test_throughput_volume_is_still_reported` is
that guarantee.

⚠️ NO new alarm threshold is invented for throughput. One day of data is not a basis for a
number, and a fabricated threshold is how the original alarm became noise.
"""

from __future__ import annotations

import pytest

from database import get_db_cursor
from services.misroute_audit_service import (
    FLOOR_FALLBACK_WARNING,
    _compute_severity,
    _floor_fallback,
    _throughput_escalation,
)
from services.escalation_log_service import record_floor_fallback

_TAG = "pytest_esc_type_probe"


@pytest.fixture
def seeded():
    """Seed both escalation kinds, then remove exactly what we inserted."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM dispatch_escalation_log WHERE capability = %s", (_TAG,))
        for _ in range(3):
            cur.execute(
                "INSERT INTO dispatch_escalation_log (capability, reason, escalation_type, created_at)"
                " VALUES (%s, %s, 'throughput', now())",
                (_TAG, "Throughput: awaiting cloud approval"),
            )
        for _ in range(2):
            cur.execute(
                "INSERT INTO dispatch_escalation_log (capability, reason, escalation_type, created_at)"
                " VALUES (%s, %s, 'floor_fallback', now())",
                (_TAG, "Floor fallback: Engineering -> Analytics"),
            )
    yield
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM dispatch_escalation_log WHERE capability = %s", (_TAG,))


def _rows_for_tag(fn):
    with get_db_cursor() as (_conn, cur):
        return [r for r in fn(cur, 24) if r.get("capability") == _TAG]


def test_floor_fallback_returns_only_floor_fallback_rows(seeded):
    rows = _rows_for_tag(_floor_fallback)
    assert sum(r["count"] for r in rows) == 2, f"expected only the 2 floor fallbacks, got {rows}"


def test_throughput_escalations_are_reported_separately(seeded):
    rows = _rows_for_tag(_throughput_escalation)
    assert sum(r["count"] for r in rows) == 3, f"expected only the 3 throughput rows, got {rows}"


# --- the regression itself, as pure dicts -----------------------------------


def _findings(floor=None, throughput=None):
    return {
        "floor_fallback": floor or [],
        "throughput_escalation": throughput or [],
        "cloud_escalation": [],
        "missing_capability": [],
        "high_failure_agents": [],
    }


def test_a_throughput_flood_no_longer_reads_as_floor_fallback():
    """The exact production shape: 1,291 throughput escalations, zero floor fallbacks."""
    out = _compute_severity(_findings(throughput=[{"capability": "factcheck_quick", "count": 1291}]))
    assert out["summary_metrics"]["floor_fallback_hits"] == 0
    assert not any("floor-fallback" in r for r in out["reasons"])


def test_throughput_volume_is_still_reported():
    """Renaming must not silence it — 1,291 real escalations stay visible."""
    out = _compute_severity(_findings(throughput=[{"capability": "factcheck_quick", "count": 1291}]))
    assert out["summary_metrics"]["throughput_escalation_hits"] == 1291


def test_real_floor_fallbacks_still_warn():
    """The alarm must still fire for what it is actually named after."""
    out = _compute_severity(_findings(floor=[{"capability": "code", "count": FLOOR_FALLBACK_WARNING + 1}]))
    assert out["severity"] == "warning"
    assert any("floor-fallback" in r for r in out["reasons"])


# --- part 2: floor fallbacks are now actually written ------------------------


def test_record_floor_fallback_persists_a_typed_row():
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM dispatch_escalation_log WHERE capability = %s", (_TAG,))
    record_floor_fallback(capability=_TAG, from_department="Engineering", to_department="Analytics")
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT escalation_type, reason FROM dispatch_escalation_log WHERE capability = %s",
                (_TAG,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        assert len(rows) == 1, f"expected exactly one row, got {rows}"
        assert rows[0]["escalation_type"] == "floor_fallback"
        assert "Engineering" in rows[0]["reason"] and "Analytics" in rows[0]["reason"]
    finally:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("DELETE FROM dispatch_escalation_log WHERE capability = %s", (_TAG,))


def test_record_floor_fallback_never_raises_into_the_dispatch_path():
    """Step 6 is the hot path — a logging failure must never break agent selection."""
    assert record_floor_fallback(capability=None, from_department=None, to_department=None) is False


def test_step_six_actually_calls_the_recorder():
    """A writer nobody calls is the bug this change exists to fix.

    `orchestration_engine` step 6 set `source = "floor_fallback"` and dropped it for the
    module's whole life. Adding `record_floor_fallback` without wiring it into step 6 would
    reproduce that exactly — and no other test in this file would notice, because they all
    call the recorder directly.

    Parsed with `ast`, not grepped: a source-grep matches this docstring and passes vacuously.
    """
    import ast
    import pathlib

    src = pathlib.Path("/app/tools/department_hq/services/orchestration_engine.py").read_text()
    tree = ast.parse(src)

    step6 = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_step_select_agent"),
        None,
    )
    assert step6 is not None, "_step_select_agent not found — the wiring target moved"

    calls = [
        c for c in ast.walk(step6) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "record_floor_fallback"
    ]
    assert calls, "step 6 never calls record_floor_fallback — floor fallbacks are invisible again"
