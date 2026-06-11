"""Unit tests for the Fitness service DB helpers."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


def _mock_cursor(row=None, rows=None):
    """Return a context-manager mock for get_db_cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    cm = _CM()
    cm.cursor = cur
    return cm


def test_log_workout_inserts_valid_workout_and_returns_iso_timestamp():
    import psycopg2.extras  # noqa: F401 - ensures psycopg2.extras.Json is attached
    from tools.fitness.services import fitness_service as svc

    logged_at = datetime(2026, 6, 11, 14, 30, 0)
    cm = _mock_cursor(row=(42, logged_at))

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.log_workout(
            user_id=7,
            workout_type="strength",
            exercises=[{"name": "Squat", "sets": 3}],
            duration_min=45,
            calories=320,
            notes="Felt solid",
        )

    assert result == {"id": 42, "logged_at": "2026-06-11T14:30:00"}
    sql, params = cm.cursor.execute.call_args.args
    assert "INSERT INTO fitness_workout_logs" in sql
    assert params[0] == 7
    assert params[1] == "strength"
    assert params[3:] == (45, 320, "Felt solid")


def test_log_workout_allows_zero_duration_at_service_layer():
    import psycopg2.extras  # noqa: F401 - ensures psycopg2.extras.Json is attached
    from tools.fitness.services import fitness_service as svc

    cm = _mock_cursor(row=(43, datetime(2026, 6, 11, 15, 0, 0)))

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.log_workout(user_id=7, workout_type="mobility", duration_min=0)

    assert result["id"] == 43
    _, params = cm.cursor.execute.call_args.args
    assert params[3] == 0


def test_get_goals_returns_empty_list_when_user_has_no_goals():
    from tools.fitness.services import fitness_service as svc

    cm = _mock_cursor(rows=[])

    with patch.object(svc, "get_db_cursor", return_value=cm):
        assert svc.get_goals(user_id=7) == []

    sql, params = cm.cursor.execute.call_args.args
    assert "FROM fitness_goals" in sql
    assert params == (7,)


def test_get_ai_context_includes_recent_workouts_and_goals():
    from tools.fitness.services import fitness_service as svc

    workouts = [
        {
            "workout_type": "strength",
            "duration_min": 45,
            "calories": 320,
            "logged_at": "2026-06-11T14:30:00",
        }
    ]
    goals = [
        {
            "goal_type": "weekly workouts",
            "current": 2.0,
            "target": 4.0,
            "unit": "sessions",
        }
    ]

    with patch.object(svc, "get_workout_history", return_value=workouts), patch.object(
        svc, "get_goals", return_value=goals
    ):
        context = svc.get_ai_context(user_id=7)

    assert "[User Fitness Context]" in context
    assert "strength | 45min | 320cal (2026-06-11)" in context
    assert "weekly workouts: 2.0/4.0 sessions" in context
