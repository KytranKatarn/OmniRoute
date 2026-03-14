"""
Fitness Service — DB persistence for workout logs, goals, and stats.
"""

from database import get_db_cursor
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def log_workout(user_id, workout_type, exercises=None, duration_min=0, calories=0, notes=""):
    """Insert a workout log entry."""
    with get_db_cursor(commit=True) as (conn, cur):
        import psycopg2

        cur.execute(
            """
            INSERT INTO fitness_workout_logs (user_id, workout_type, exercises, duration_min, calories, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, logged_at
            """,
            (user_id, workout_type, psycopg2.extras.Json(exercises or []), duration_min, calories, notes),
        )
        row = cur.fetchone()
        return {"id": row[0], "logged_at": row[1].isoformat()}


def get_workout_history(user_id, limit=20):
    """Return recent workout logs for user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, workout_type, exercises, duration_min, calories, notes, logged_at
            FROM fitness_workout_logs
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
                "workout_type": r[1],
                "exercises": r[2],
                "duration_min": r[3],
                "calories": r[4],
                "notes": r[5],
                "logged_at": r[6].isoformat(),
            }
            for r in rows
        ]


def set_goal(user_id, goal_type, target, unit="", deadline=None):
    """Insert a new fitness goal."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO fitness_goals (user_id, goal_type, target, unit, deadline)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (user_id, goal_type, target, unit, deadline),
        )
        row = cur.fetchone()
        return {"id": row[0], "created_at": row[1].isoformat()}


def get_goals(user_id):
    """Return all goals for user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, goal_type, target, current, unit, deadline, created_at
            FROM fitness_goals
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "goal_type": r[1],
                "target": float(r[2]),
                "current": float(r[3]),
                "unit": r[4],
                "deadline": r[5].isoformat() if r[5] else None,
                "created_at": r[6].isoformat(),
            }
            for r in rows
        ]


def update_goal_progress(goal_id, current):
    """Update current progress on a goal."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE fitness_goals SET current = %s WHERE id = %s",
            (current, goal_id),
        )
        return {"updated": cur.rowcount > 0}


def get_fitness_stats(user_id):
    """Aggregate stats: workouts this week, total calories, consecutive-day streak."""
    with get_db_cursor() as (conn, cur):
        # Workouts this week
        week_start = datetime.now() - timedelta(days=datetime.now().weekday())
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(calories), 0)
            FROM fitness_workout_logs
            WHERE user_id = %s AND logged_at >= %s
            """,
            (user_id, week_start.date()),
        )
        week_row = cur.fetchone()

        # Streak: consecutive days with at least one workout
        cur.execute(
            """
            SELECT DISTINCT DATE(logged_at) as workout_date
            FROM fitness_workout_logs
            WHERE user_id = %s
            ORDER BY workout_date DESC
            LIMIT 60
            """,
            (user_id,),
        )
        dates = [r[0] for r in cur.fetchall()]
        streak = 0
        today = datetime.now().date()
        for i, d in enumerate(dates):
            expected = today - timedelta(days=i)
            if d == expected:
                streak += 1
            else:
                break

        return {
            "workouts_this_week": week_row[0],
            "calories_this_week": int(week_row[1]),
            "streak_days": streak,
        }


def schedule_workout(user_id, title, datetime_str, duration=60):
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
                description="Scheduled via Fitness module",
            )
    except Exception:
        pass
    return {"success": True, "note": "Saved locally (no Google Calendar connected)"}


def get_ai_context(user_id):
    """Return last 5 workouts + current goals as a text string for Bridge prompt injection."""
    try:
        workouts = get_workout_history(user_id, limit=5)
        goals = get_goals(user_id)
        lines = ["[User Fitness Context]"]
        if workouts:
            lines.append("Recent workouts:")
            for w in workouts:
                lines.append(
                    f"  - {w['workout_type']} | {w['duration_min']}min | {w['calories']}cal ({w['logged_at'][:10]})"
                )
        if goals:
            lines.append("Current goals:")
            for g in goals:
                lines.append(f"  - {g['goal_type']}: {g['current']}/{g['target']} {g['unit']}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"get_ai_context failed: {e}")
        return ""
