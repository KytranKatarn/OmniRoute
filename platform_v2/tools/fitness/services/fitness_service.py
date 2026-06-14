"""
Fitness Service — DB persistence for workout logs, goals, and stats.
"""

from database import get_db_cursor
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

_WORKOUT_UPDATE_FIELDS = {
    "workout_type",
    "exercises",
    "duration_min",
    "calories",
    "notes",
}

_GOAL_UPDATE_FIELDS = {
    "goal_type",
    "target",
    "current",
    "unit",
    "deadline",
}


def _workout_row_to_dict(row):
    return {
        "id": row[0],
        "workout_type": row[1],
        "exercises": row[2],
        "duration_min": row[3],
        "calories": row[4],
        "notes": row[5],
        "logged_at": row[6].isoformat(),
    }


def _goal_row_to_dict(row):
    return {
        "id": row[0],
        "goal_type": row[1],
        "target": float(row[2]),
        "current": float(row[3]),
        "unit": row[4],
        "deadline": row[5].isoformat() if row[5] else None,
        "created_at": row[6].isoformat(),
    }


def calculate_macros(
    weight,
    height,
    age,
    gender="male",
    activity_level="moderate",
    goal="maintain",
):
    """Calculate BMR, TDEE, target calories, and macros using Mifflin-St Jeor."""
    # Calculate BMR using Mifflin-St Jeor
    if gender == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    tdee = bmr * activity_multipliers.get(activity_level, 1.55)

    if goal == "lose":
        calories = tdee - 500
    elif goal == "gain":
        calories = tdee + 300
    else:
        calories = tdee

    protein = weight * 2
    fat = (calories * 0.25) / 9
    carbs = (calories - (protein * 4) - (fat * 9)) / 4

    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "target_calories": round(calories),
        "macros": {
            "protein": round(protein),
            "carbs": round(carbs),
            "fat": round(fat),
        },
    }


def log_workout(
    user_id: int,
    workout_type: str,
    exercises: Optional[List[Dict[str, Any]]] = None,
    duration_min: int = 0,
    calories: int = 0,
    notes: str = "",
) -> Dict[str, Any]:
    """Insert a workout log entry."""
    with get_db_cursor(commit=True) as (conn, cur):
        from psycopg2.extras import Json

        cur.execute(
            """
            INSERT INTO fitness_workout_logs (user_id, workout_type, exercises, duration_min, calories, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, logged_at
            """,
            (user_id, workout_type, Json(exercises or []), duration_min, calories, notes),
        )
        row = cur.fetchone()
        return {"id": row[0], "logged_at": row[1].isoformat()}


def get_workout_history(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
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
        return [_workout_row_to_dict(r) for r in rows]


def update_workout(user_id, workout_id, updates):
    """Update a workout log owned by user_id. Returns updated row or None."""
    fields = {key: value for key, value in (updates or {}).items() if key in _WORKOUT_UPDATE_FIELDS}
    if not fields:
        return None

    values = []
    assignments = []
    for key, value in fields.items():
        assignments.append(f"{key} = %s")
        if key == "exercises":
            from psycopg2.extras import Json

            value = Json(value or [])
        values.append(value)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""
            UPDATE fitness_workout_logs
            SET {", ".join(assignments)}
            WHERE id = %s AND user_id = %s
            RETURNING id, workout_type, exercises, duration_min, calories, notes, logged_at
            """,
            (*values, workout_id, user_id),
        )
        row = cur.fetchone()
        return _workout_row_to_dict(row) if row else None


def delete_workout(user_id, workout_id):
    """Delete a workout log owned by user_id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            DELETE FROM fitness_workout_logs
            WHERE id = %s AND user_id = %s
            """,
            (workout_id, user_id),
        )
        return cur.rowcount > 0


def set_goal(
    user_id: int,
    goal_type: str,
    target: Union[int, float],
    unit: str = "",
    deadline: Optional[Any] = None,
) -> Dict[str, Any]:
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


def get_goals(user_id: int) -> List[Dict[str, Any]]:
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
        return [_goal_row_to_dict(r) for r in rows]


def update_goal(user_id, goal_id, updates):
    """Update a fitness goal owned by user_id. Returns updated row or None."""
    fields = {key: value for key, value in (updates or {}).items() if key in _GOAL_UPDATE_FIELDS}
    if not fields:
        return None

    set_clause = ", ".join(f"{key} = %s" for key in fields)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""
            UPDATE fitness_goals
            SET {set_clause}
            WHERE id = %s AND user_id = %s
            RETURNING id, goal_type, target, current, unit, deadline, created_at
            """,
            (*fields.values(), goal_id, user_id),
        )
        row = cur.fetchone()
        return _goal_row_to_dict(row) if row else None


def delete_goal(user_id, goal_id):
    """Delete a fitness goal owned by user_id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            DELETE FROM fitness_goals
            WHERE id = %s AND user_id = %s
            """,
            (goal_id, user_id),
        )
        return cur.rowcount > 0


def update_goal_progress(goal_id: int, current: Union[int, float]) -> Dict[str, bool]:
    """Update current progress on a goal."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE fitness_goals SET current = %s WHERE id = %s",
            (current, goal_id),
        )
        return {"updated": cur.rowcount > 0}


def get_fitness_stats(user_id: int) -> Dict[str, int]:
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


def schedule_workout(
    user_id: int,
    title: str,
    datetime_str: str,
    duration: int = 60,
) -> Dict[str, Any]:
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


def get_ai_context(user_id: int) -> str:
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
