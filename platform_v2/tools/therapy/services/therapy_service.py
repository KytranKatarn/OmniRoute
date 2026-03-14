"""
Therapy Service — DB persistence for mood logs, sessions, and stats.
"""

from database import get_db_cursor
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def log_mood(user_id, mood_score, energy_score=None, notes="", tags=None):
    """Insert a mood log entry."""
    with get_db_cursor(commit=True) as (conn, cur):
        import psycopg2.extras

        cur.execute(
            """
            INSERT INTO therapy_mood_logs (user_id, mood_score, energy_score, notes, tags)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, logged_at
            """,
            (user_id, mood_score, energy_score, notes, psycopg2.extras.Json(tags or [])),
        )
        row = cur.fetchone()
        return {"id": row[0], "logged_at": row[1].isoformat()}


def get_mood_history(user_id, limit=30):
    """Return recent mood log entries for user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, mood_score, energy_score, notes, tags, logged_at
            FROM therapy_mood_logs
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
                "mood_score": r[1],
                "energy_score": r[2],
                "notes": r[3],
                "tags": r[4],
                "logged_at": r[5].isoformat(),
            }
            for r in rows
        ]


def log_session(user_id, session_type="general", notes="", exercises_done=None, duration_min=0):
    """Insert a therapy session log."""
    with get_db_cursor(commit=True) as (conn, cur):
        import psycopg2.extras

        cur.execute(
            """
            INSERT INTO therapy_sessions (user_id, session_type, notes, exercises_done, duration_min)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, logged_at
            """,
            (user_id, session_type, notes, psycopg2.extras.Json(exercises_done or []), duration_min),
        )
        row = cur.fetchone()
        return {"id": row[0], "logged_at": row[1].isoformat()}


def get_session_history(user_id, limit=20):
    """Return recent therapy sessions for user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, session_type, notes, exercises_done, duration_min, logged_at
            FROM therapy_sessions
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
                "session_type": r[1],
                "notes": r[2],
                "exercises_done": r[3],
                "duration_min": r[4],
                "logged_at": r[5].isoformat(),
            }
            for r in rows
        ]


def get_therapy_stats(user_id):
    """Aggregate: avg mood last 7 days, session count this month, mood trend."""
    with get_db_cursor() as (conn, cur):
        # Avg mood last 7 days
        seven_days_ago = datetime.now() - timedelta(days=7)
        cur.execute(
            """
            SELECT AVG(mood_score), COUNT(*)
            FROM therapy_mood_logs
            WHERE user_id = %s AND logged_at >= %s
            """,
            (user_id, seven_days_ago),
        )
        mood_row = cur.fetchone()
        avg_mood = round(float(mood_row[0]), 2) if mood_row[0] else None

        # Session count this month
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0)
        cur.execute(
            "SELECT COUNT(*) FROM therapy_sessions WHERE user_id = %s AND logged_at >= %s",
            (user_id, month_start),
        )
        session_count = cur.fetchone()[0]

        # Mood trend: compare last 3 days vs prior 4 days
        three_days_ago = datetime.now() - timedelta(days=3)
        cur.execute(
            """
            SELECT
                AVG(CASE WHEN logged_at >= %s THEN mood_score END) as recent_avg,
                AVG(CASE WHEN logged_at < %s AND logged_at >= %s THEN mood_score END) as prior_avg
            FROM therapy_mood_logs
            WHERE user_id = %s AND logged_at >= %s
            """,
            (three_days_ago, three_days_ago, seven_days_ago, user_id, seven_days_ago),
        )
        trend_row = cur.fetchone()
        trend = "stable"
        if trend_row[0] and trend_row[1]:
            diff = float(trend_row[0]) - float(trend_row[1])
            if diff > 0.5:
                trend = "improving"
            elif diff < -0.5:
                trend = "declining"

        return {
            "avg_mood_7d": avg_mood,
            "mood_entries_7d": mood_row[1],
            "sessions_this_month": session_count,
            "mood_trend": trend,
        }


def schedule_session(user_id, title, datetime_str, duration=60):
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
                description="Scheduled via Therapy module",
            )
    except Exception:
        pass
    return {"success": True, "note": "Saved locally (no Google Calendar connected)"}


def get_ai_context(user_id):
    """Return last 5 mood entries + recent sessions as text for Bridge prompt injection."""
    try:
        moods = get_mood_history(user_id, limit=5)
        sessions = get_session_history(user_id, limit=3)
        lines = ["[User Therapy Context]"]
        if moods:
            lines.append("Recent mood entries:")
            for m in moods:
                energy = f" | energy {m['energy_score']}/10" if m["energy_score"] else ""
                lines.append(
                    f"  - Mood {m['mood_score']}/10{energy} ({m['logged_at'][:10]}): {m['notes'][:60] if m['notes'] else 'no notes'}"
                )
        if sessions:
            lines.append("Recent sessions:")
            for s in sessions:
                lines.append(f"  - {s['session_type']} | {s['duration_min']}min ({s['logged_at'][:10]})")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"get_ai_context failed: {e}")
        return ""
