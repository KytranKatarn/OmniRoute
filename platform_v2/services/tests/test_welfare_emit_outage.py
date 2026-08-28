"""#4130 FIX-3 — structural welfare-emit failures must be LOUD, not debug-swallowed.

Per-event emit failures were already loud (welfare_emit._record_emit_failure →
governance_audit_log + system_notification). FIX-3 closes the remaining SILENT
structural paths: creed_emit/welfare_emit unavailable, or the emit raising — each
previously only logger.warning'd. record_welfare_emit_outage() makes them loud on
a FRESH connection (so it works even if the caller's cursor is poisoned), and
emit_welfare_snapshots() never raises.

INTEGRATION tests — need a live DB. Run from platform_v2/:
    docker exec archie_platform python3 -m pytest services/tests/test_welfare_emit_outage.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor

from services.welfare_emit import record_welfare_emit_outage
from services.welfare_governance_service import emit_welfare_snapshots

_MARK = "ZZTEST_W4130_FIX3"


def _purge():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM governance_audit_log WHERE reason LIKE %s", (f"%{_MARK}%",))
        cur.execute("DELETE FROM system_notifications WHERE message LIKE %s", (f"%{_MARK}%",))


@pytest.fixture(autouse=True)
def _cleanup():
    _purge()
    yield
    _purge()


def _count_outage_rows(marker):
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS n FROM governance_audit_log "
            "WHERE event_type = 'welfare_emit_outage' AND reason LIKE %s",
            (f"%{marker}%",),
        )
        audit = cur.fetchone()["n"]
        cur.execute(
            "SELECT COUNT(*) AS n FROM system_notifications " "WHERE source = 'welfare_emit' AND message LIKE %s",
            (f"%{marker}%",),
        )
        notif = cur.fetchone()["n"]
    return audit, notif


def test_record_welfare_emit_outage_writes_audit_and_notification():
    reason = f"{_MARK} creed_emit unavailable"
    record_welfare_emit_outage(reason)
    audit, notif = _count_outage_rows(_MARK)
    assert audit == 1, "outage must write a governance_audit_log row (event_type=welfare_emit_outage)"
    assert notif == 1, "outage must write a system_notification (source=welfare_emit)"


def test_emit_welfare_snapshots_records_outage_when_emit_raises(monkeypatch):
    boom = f"{_MARK} simulated emit failure"

    def _raise(*a, **k):
        raise RuntimeError(boom)

    # emit_welfare_snapshots imports emit_welfare_events lazily from this module.
    monkeypatch.setattr("services.welfare_emit.emit_welfare_events", _raise)

    with get_db_cursor() as (conn, cur):
        # snaps/break_cfg passed so we skip gather/load and isolate the emit-raise path.
        summary = emit_welfare_snapshots(cur, snaps=[], break_cfg={})

    # Never raises → returns the clean zero summary.
    assert summary == {"built": 0, "emitted": 0, "skipped": 0, "failed": 0}
    # And the structural failure was recorded loudly (fresh connection, so it
    # persists even though the wrapper swallowed the exception).
    audit, notif = _count_outage_rows(boom)
    assert audit >= 1, "a raised emit must record a welfare_emit_outage audit row"
    assert notif >= 1, "a raised emit must record a system_notification"
