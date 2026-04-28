"""audit_summary.py — writes a vault_note to knowledge_base after each nightly audit.

Records per-domain gap counts, language coverage, and batch routing stats so
the team can track translation health over time without reading raw DB tables.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from database import get_db_cursor

logger = logging.getLogger("agent_loop")

AUDIT_CATEGORY = "translation"
AUDIT_TAGS = ["translation-audit", "probe", "nightly"]


def store_audit_summary(totals: dict) -> int | None:
    """Insert a vault_note into knowledge_base with audit totals.

    Returns the inserted knowledge_base id, or None on failure.
    """
    run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    title = f"Translation Audit — {run_date} — {totals.get('gaps_found', 0)} gaps"
    content = (
        f"## P.R.O.B.E. Nightly Translation Audit — {run_date}\n\n"
        f"### Summary\n"
        f"- Total gaps found: {totals.get('gaps_found', 0)}\n"
        f"- Domain gaps: {totals.get('domain_gaps_found', 0)}\n"
        f"- Auto-fixed (platform): {totals.get('auto_fixed', 0)}\n"
        f"- Routed to review: {totals.get('routed', 0)}\n"
        f"- Translate batches sent: {totals.get('domain_batches_sent', 0)}\n"
        f"- Domain gaps routed: {totals.get('domain_gaps_routed', 0)}\n"
        f"- Duration: {totals.get('duration_ms', 0)}ms\n\n"
        f"### Raw Totals\n"
        f"```json\n{json.dumps(totals, indent=2)}\n```\n"
    )
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO knowledge_base
                       (memory_type, title, content, category, tags, importance_score, created_at)
                   VALUES ('vault_note', %s, %s, %s, %s, 0.75, NOW())
                   RETURNING id""",
                (title, content, AUDIT_CATEGORY, AUDIT_TAGS),
            )
            kb_id = cur.fetchone()["id"]
            logger.info("[AuditSummary] vault_note stored kb_id=%d title=%r", kb_id, title)
            return kb_id
    except Exception:  # noqa: BLE001
        logger.exception("[AuditSummary] failed to store vault_note")
        return None
