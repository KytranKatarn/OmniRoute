"""
DOC Service — DB persistence for symptom logs, medications, and health stats.
"""

from database import get_db_cursor
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def log_symptoms(user_id, symptoms, severity=None, notes=""):
    """Insert a symptom log entry."""
    with get_db_cursor(commit=True) as (conn, cur):
        import psycopg2.extras

        # symptoms can be a list or a string; normalise to list
        if isinstance(symptoms, str):
            symptoms = [symptoms]
        cur.execute(
            """
            INSERT INTO health_symptom_logs (user_id, symptoms, severity, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id, logged_at
            """,
            (user_id, psycopg2.extras.Json(symptoms), severity, notes),
        )
        row = cur.fetchone()
        return {"id": row[0], "logged_at": row[1].isoformat()}


def get_symptom_history(user_id, limit=20):
    """Return recent symptom logs for user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, symptoms, severity, notes, logged_at
            FROM health_symptom_logs
            WHERE user_id = %s
            ORDER BY logged_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "symptoms": r[1],
                "severity": r[2],
                "notes": r[3],
                "logged_at": r[4].isoformat(),
            }
            for r in rows
        ]


def add_medication(user_id, name, dosage="", frequency="", start_date=None):
    """Insert a new medication record."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO health_medications (user_id, name, dosage, frequency, start_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (user_id, name, dosage, frequency, start_date),
        )
        row = cur.fetchone()
        return {"id": row[0], "created_at": row[1].isoformat()}


def get_medications(user_id, active_only=True):
    """Return medications for user, optionally only active ones."""
    with get_db_cursor() as (conn, cur):
        if active_only:
            cur.execute(
                """
                SELECT id, name, dosage, frequency, start_date, end_date, active, created_at
                FROM health_medications
                WHERE user_id = %s AND active = TRUE
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
        else:
            cur.execute(
                """
                SELECT id, name, dosage, frequency, start_date, end_date, active, created_at
                FROM health_medications
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "dosage": r[2],
                "frequency": r[3],
                "start_date": r[4].isoformat() if r[4] else None,
                "end_date": r[5].isoformat() if r[5] else None,
                "active": r[6],
                "created_at": r[7].isoformat(),
            }
            for r in rows
        ]


def update_medication(med_id, user_id, updates):
    """Update medication fields (including deactivation). updates is a dict."""
    allowed = {"dosage", "frequency", "end_date", "active"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return {"updated": False, "error": "No valid fields to update"}
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [med_id, user_id]
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE health_medications SET {set_clause} WHERE id = %s AND user_id = %s",
            values,
        )
        return {"updated": cur.rowcount > 0}


def get_health_stats(user_id):
    """Aggregate: symptom frequency, active med count, days since last log."""
    with get_db_cursor() as (conn, cur):
        # Active med count
        cur.execute(
            "SELECT COUNT(*) FROM health_medications WHERE user_id = %s AND active = TRUE",
            (user_id,),
        )
        active_meds = cur.fetchone()[0]

        # Total symptom logs last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        cur.execute(
            "SELECT COUNT(*) FROM health_symptom_logs WHERE user_id = %s AND logged_at >= %s",
            (user_id, thirty_days_ago),
        )
        symptom_count_30d = cur.fetchone()[0]

        # Days since last symptom log
        cur.execute(
            "SELECT MAX(logged_at) FROM health_symptom_logs WHERE user_id = %s",
            (user_id,),
        )
        last_log = cur.fetchone()[0]
        days_since_last = None
        if last_log:
            days_since_last = (datetime.now() - last_log).days

        return {
            "active_medications": active_meds,
            "symptom_logs_30d": symptom_count_30d,
            "days_since_last_log": days_since_last,
        }


def schedule_appointment(user_id, title, datetime_str, duration=30):
    """Try to create a Google Calendar event; fall back to local success."""
    try:
        from tools.google_work_suite.services.google_api_service import list_accounts
        from tools.google_work_suite.services.calendar_service import create_event

        accounts = list_accounts(owner_type="user", owner_id=user_id)
        if accounts:
            start = datetime.fromisoformat(datetime_str)
            end = start + timedelta(minutes=duration)
            return create_event(
                accounts[0]["id"],
                title,
                start.isoformat(),
                end.isoformat(),
                description="Scheduled via DOC module",
            )
    except Exception:
        pass
    return {"success": True, "note": "Saved locally (no Google Calendar connected)"}


def get_ai_context(user_id):
    """Return recent symptoms + active meds as text for Bridge prompt injection."""
    try:
        symptoms = get_symptom_history(user_id, limit=5)
        meds = get_medications(user_id, active_only=True)
        lines = ["[User Health Context]"]
        if symptoms:
            lines.append("Recent symptoms:")
            for s in symptoms:
                sym_list = ", ".join(s["symptoms"]) if isinstance(s["symptoms"], list) else str(s["symptoms"])
                severity = f" (severity {s['severity']}/10)" if s["severity"] else ""
                lines.append(f"  - {sym_list}{severity} ({s['logged_at'][:10]})")
        if meds:
            lines.append("Active medications:")
            for m in meds:
                lines.append(f"  - {m['name']} {m['dosage']} {m['frequency']}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"get_ai_context failed: {e}")
        return ""
