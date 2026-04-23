"""A.R.C.H.I.E. Briefing Service — Director Reports + Morning Briefing + Triage.

Handles the hierarchy flow: Directors report UP → A.R.C.H.I.E. triages → Kytran gets the relevant parts.

Functions:
    submit_director_report() — called by agent loop jobs to report findings
    run_triage() — every 5 min, decides what to escalate to Kytran
    run_morning_briefing() — daily synthesis of overnight director reports
"""

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Kytran's user_id in the platform `users` table — target for director-report
# chat threads. Directors post their escalations as messages into a per-director
# conversation owned by this user so Kytran sees them in the chat sidebar
# alongside Telegram. Fallback value; overridden by DB lookup if available.
_KYTRAN_USER_ID = 2


def _get_owner_user_id():
    """Resolve the chat owner (Kytran) — prefer DB, fall back to constant."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM users WHERE role = 'admin' AND username = 'Kytran' LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                return row["id"] if isinstance(row, dict) else row[0]
    except Exception as e:
        logger.debug("briefing_service: owner lookup fell back to constant (%s)", e)
    return _KYTRAN_USER_ID


def _ensure_director_thread(user_id, director_agent):
    """Find or create the persistent chat thread for this director's reports.

    One thread per director (V.I.G.I.L., B.A.S.E., K.I.N., etc.) — their
    reports accumulate in a single conversation so Kytran can scroll history
    and reply inline instead of context-switching to Telegram.
    """
    try:
        from database import get_db_cursor

        topic = f"{director_agent} Reports"
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id FROM unified_conversations "
                "WHERE user_id = %s AND topic = %s AND status = 'active' LIMIT 1",
                (user_id, topic),
            )
            row = cur.fetchone()
            if row:
                return row["id"] if isinstance(row, dict) else row[0]

            cur.execute(
                "INSERT INTO unified_conversations (user_id, topic, title, agent_target) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (user_id, topic, topic, director_agent),
            )
            row = cur.fetchone()
            conn.commit()
            cid = row["id"] if isinstance(row, dict) else row[0]
            logger.info(
                "briefing_service: created director thread #%d for %s", cid, director_agent
            )
            return cid
    except Exception as e:
        logger.error("briefing_service: _ensure_director_thread failed: %s", e)
        return None


def _mirror_to_chat(director_agent, title, summary, severity, report_id):
    """Post the escalated report as a chat message (Phase 1f, ADR-001).

    A.R.C.H.I.E. is the unified voice, so the chat inbox mirrors every
    Telegram escalation. Kytran can click the director's thread in the
    sidebar and reply inline — future phase wires replies back to A.R.C.H.I.E.
    for intent parsing + delegation.

    Writes directly to unified_messages because conversation_service has two
    overloaded save_message definitions; we want the (channel, direction,
    sender, metadata) semantics specifically, not the chat-role mapping.
    """
    try:
        user_id = _get_owner_user_id()
        conv_id = _ensure_director_thread(user_id, director_agent)
        if not conv_id:
            return

        from database import get_db_cursor

        icon = {"critical": "🔴", "high": "🟡", "medium": "🟢", "low": "ℹ️"}.get(severity, "•")
        content = f"{icon} **{title}**\n\n{summary}"
        metadata = {
            "report_id": report_id,
            "severity": severity,
            "title": title,
        }
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO unified_messages
                   (conversation_id, channel, direction, sender, content, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    conv_id,
                    "director_report",
                    "in",
                    director_agent,
                    content,
                    json.dumps(metadata),
                ),
            )
            cur.execute(
                "UPDATE unified_conversations SET last_activity = NOW(), updated_at = NOW() "
                "WHERE id = %s",
                (conv_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error(
            "briefing_service: _mirror_to_chat failed for report #%d: %s", report_id, e
        )


def submit_director_report(
    department,
    director_agent,
    severity,
    category,
    title,
    summary,
    details=None,
):
    """Director submits a report UP the hierarchy.

    Instead of sending directly to Telegram, directors write here.
    A.R.C.H.I.E. triages and decides what Kytran needs to see.

    Args:
        department: e.g. "Security & Compliance"
        director_agent: e.g. "V.I.G.I.L."
        severity: critical, high, medium, low
        category: security, operations, engineering, etc.
        title: Short title
        summary: What happened
        details: Optional dict with extra context
    """
    # 5-minute dedup window — same director + category + title = one report
    window = int(time.time() // 300)
    raw = f"{director_agent}:{category}:{title}:{window}"
    dedup_key = hashlib.sha256(raw.encode()).hexdigest()[:32]

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO director_reports
                   (department, director_agent, severity, category, title, summary, details, dedup_key)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (dedup_key) DO NOTHING
                   RETURNING id""",
                (
                    department,
                    director_agent,
                    severity,
                    category,
                    title,
                    summary,
                    json.dumps(details) if details else "{}",
                    dedup_key,
                ),
            )
            report_id = cur.fetchone()
            conn.commit()

            if report_id is None:
                logger.debug(
                    "director_report deduped (key=%s): [%s] %s from %s — %s",
                    dedup_key, severity, category, director_agent, title,
                )
                return None

            rid = report_id["id"] if isinstance(report_id, dict) else report_id[0]
            logger.info(
                "director_report #%d: [%s] %s from %s — %s",
                rid, severity, category, director_agent, title,
            )

            # Critical reports get immediate escalation
            if severity == "critical":
                _escalate_report(rid, department, director_agent, title, summary, severity)

            return rid

    except Exception as e:
        logger.error("briefing_service: submit_director_report failed: %s", e)
        return None


def run_triage():
    """Triage un-escalated director reports.

    Runs every 5 minutes. A.R.C.H.I.E. decides per report:
    - critical/high → escalate to Kytran (Telegram if offline, chat if online)
    - medium → log, escalate only if pattern repeats
    - low → ignore (included in next morning briefing)
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, department, director_agent, severity, category, title, summary
                   FROM director_reports
                   WHERE escalated = FALSE AND severity IN ('critical', 'high')
                   AND created_at > NOW() - INTERVAL '1 hour'
                   ORDER BY CASE severity
                       WHEN 'critical' THEN 1
                       WHEN 'high' THEN 2
                       ELSE 3
                   END, created_at ASC
                   LIMIT 10"""
            )
            reports = cur.fetchall()

        if not reports:
            return 0

        escalated = 0
        for r in reports:
            rid = r["id"] if isinstance(r, dict) else r[0]
            dept = r["department"] if isinstance(r, dict) else r[1]
            agent = r["director_agent"] if isinstance(r, dict) else r[2]
            severity = r["severity"] if isinstance(r, dict) else r[3]
            title = r["title"] if isinstance(r, dict) else r[5]
            summary = r["summary"] if isinstance(r, dict) else r[6]

            _escalate_report(rid, dept, agent, title, summary, severity)
            escalated += 1

        logger.info("briefing_service: triage escalated %d reports", escalated)
        return escalated

    except Exception as e:
        logger.error("briefing_service: run_triage failed: %s", e)
        return 0


def _escalate_report(report_id, department, director_agent, title, summary, severity):
    """Send a director report to Kytran via Telegram AND the chat inbox.

    A.R.C.H.I.E. is the unified voice (ADR-001). Every escalation:
      1. goes to Telegram (out-of-app alerts)
      2. also posts into the director's chat thread (in-app inbox)

    Kytran sees both. In chat he can click in and discuss inline; Telegram
    is the push notification. Failure in one path doesn't break the other.
    """
    try:
        from services.telegram_service import send

        send(
            category="security" if severity == "critical" else "system",
            title=title,
            message=summary,
            source_agent=director_agent,
            source_department=department,
            force=(severity == "critical"),
        )

        # Mirror into chat inbox — never block the escalation on this path.
        _mirror_to_chat(director_agent, title, summary, severity, report_id)

        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """UPDATE director_reports
                   SET escalated = TRUE, escalation_channel = 'telegram', escalated_at = NOW()
                   WHERE id = %s""",
                (report_id,),
            )
            conn.commit()

    except Exception as e:
        logger.error("briefing_service: _escalate_report failed for #%d: %s", report_id, e)


def run_morning_briefing():
    """Synthesize overnight director reports into a morning briefing.

    Queries reports from the last 12 hours, groups by department,
    sends through dolphin3-8k for synthesis, delivers via Telegram.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT department, director_agent, severity, title, summary
                   FROM director_reports
                   WHERE created_at > NOW() - INTERVAL '12 hours'
                   ORDER BY department, created_at"""
            )
            reports = cur.fetchall()

        if not reports:
            logger.info("briefing_service: no overnight reports — skipping briefing")
            return

        # Group by department
        by_dept = {}
        for r in reports:
            dept = r["department"] if isinstance(r, dict) else r[0]
            if dept not in by_dept:
                by_dept[dept] = []
            by_dept[dept].append({
                "agent": r["director_agent"] if isinstance(r, dict) else r[1],
                "severity": r["severity"] if isinstance(r, dict) else r[2],
                "title": r["title"] if isinstance(r, dict) else r[3],
                "summary": r["summary"] if isinstance(r, dict) else r[4],
            })

        # Build raw briefing data for LLM
        raw_data = "Overnight director reports (last 12 hours):\n\n"
        for dept, items in by_dept.items():
            raw_data += f"## {dept}\n"
            for item in items:
                raw_data += f"- [{item['severity'].upper()}] {item['title']}: {item['summary']}\n"
            raw_data += "\n"

        # Send through personality engine for synthesis
        from services.archie_voice_service import format_message

        briefing = format_message(
            category="info",
            title="Morning Briefing",
            raw_message=raw_data,
            source_agent="A.R.C.H.I.E.",
            source_department="Executive Office",
        )

        # Deliver via Telegram
        from services.telegram_service import send

        send(
            category="info",
            title="Morning Briefing",
            message=briefing,
            source_agent="A.R.C.H.I.E.",
            source_department="Executive Office",
            force=True,  # always deliver briefings
        )

        logger.info(
            "briefing_service: morning briefing sent (%d reports from %d departments)",
            len(reports), len(by_dept),
        )

    except Exception as e:
        logger.error("briefing_service: run_morning_briefing failed: %s", e)


def get_recent_reports(hours=24, limit=50):
    """Get recent director reports for display in the chat/COMs tab."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, department, director_agent, severity, category,
                          title, summary, escalated, created_at
                   FROM director_reports
                   WHERE created_at > NOW() - INTERVAL '%s hours'
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (hours, limit),
            )
            return cur.fetchall()

    except Exception as e:
        logger.error("briefing_service: get_recent_reports failed: %s", e)
        return []
