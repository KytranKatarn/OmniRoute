"""A.R.C.H.I.E. Briefing Service — Director Reports + Morning Briefing + Triage.

Handles the hierarchy flow: Directors report UP → A.R.C.H.I.E. triages → Kytran gets the relevant parts.

Functions:
    submit_director_report() — called by agent loop jobs to report findings
    run_triage() — every 5 min, decides what to escalate to Kytran
    run_morning_briefing() — daily synthesis of overnight director reports
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)


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
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO director_reports
                   (department, director_agent, severity, category, title, summary, details)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    department,
                    director_agent,
                    severity,
                    category,
                    title,
                    summary,
                    json.dumps(details) if details else "{}",
                ),
            )
            report_id = cur.fetchone()
            rid = report_id["id"] if isinstance(report_id, dict) else report_id[0]
            conn.commit()
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
    """Send a director report to Kytran via Telegram (using A.R.C.H.I.E.'s voice)."""
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
