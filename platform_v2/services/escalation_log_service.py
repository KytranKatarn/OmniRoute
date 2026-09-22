"""Write floor-fallback escalations so the audit can actually see them (#6834).

WHY THIS EXISTS: `dispatch_escalation_log` had exactly ONE writer — the cloud/throughput
path in `department_dispatcher`. `orchestration_engine` step 6 sets `source =
"floor_fallback"` as a LOCAL VARIABLE and drops it on the floor, so a same-floor department
substitution was never recorded anywhere. Meanwhile `misroute_audit_service._floor_fallback`
selected every row of that table and reported the total as "floor_fallback_hits", so the
audit alarmed permanently on the cloud number under a floor-fallback name while genuine
floor fallbacks were unmonitored but APPEARED monitored.

Measured 2026-09-22 over 24h before the fix: 1,291 throughput escalations, ZERO floor
fallbacks recorded, alarm firing at 1,345 against a threshold of 20.

⚠️ THIS RUNS IN THE DISPATCH HOT PATH (step 6, agent selection). It must NEVER raise and
never block: telemetry that can break agent selection is worse than no telemetry. Every
failure returns False and logs at debug.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

ESCALATION_TYPE = "floor_fallback"


def record_floor_fallback(
    capability: Optional[str],
    from_department: Optional[str],
    to_department: Optional[str],
    agent_id: Optional[int] = None,
    module_id: Optional[str] = None,
) -> bool:
    """Record one same-floor department substitution. Returns True only on a real insert.

    Returns False — never raises — on missing inputs or any DB problem, because the caller
    is choosing an agent for a live dispatch and must not be interrupted by bookkeeping.
    """
    if not capability or not from_department or not to_department:
        # Not an error worth logging loudly: callers may legitimately lack a department
        # (e.g. an unmapped capability), and a half-identified row is worse than no row.
        return False

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO dispatch_escalation_log
                    (capability, reason, escalation_type, original_agent_id, module_id, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    str(capability),
                    f"Floor fallback: {from_department} -> {to_department}",
                    ESCALATION_TYPE,
                    agent_id,
                    module_id,
                ),
            )
        return True
    except Exception as exc:  # noqa: BLE001 - telemetry must never break dispatch
        logger.debug("record_floor_fallback failed (non-fatal): %s", exc)
        return False
