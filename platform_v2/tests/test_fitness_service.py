"""Unit tests for the Fitness service DB helpers."""

from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.modstub import stub_module_scoped

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


@pytest.fixture(scope="module", autouse=True)
def _isolate_fitness_package():
    """Load fitness_service without running tools/fitness/__init__.py.

    The package __init__ imports routes.py, which imports the department dispatcher,
    which does `from db import _get_db_password` — a bare ``db`` that only resolves at
    runtime once ai_bridge/ is on sys.path. These unit tests exercise only the service
    layer, so we synthesize the tools.fitness package (pointing at the real directory)
    and skip __init__ entirely; submodule imports still hit the real service file.
    """
    pkg = types.ModuleType("tools.fitness")
    pkg.__path__ = [str(PLATFORM_ROOT / "tools" / "fitness")]
    with stub_module_scoped("tools.fitness", pkg):
        yield


def _mock_cursor(row=None, rows=None, rowcount=0):
    """Return a context-manager mock for get_db_cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    cur.rowcount = rowcount
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


def test_update_workout_checks_user_id_and_returns_updated_row():
    import psycopg2.extras  # noqa: F401 - ensures psycopg2.extras.Json is attached
    from tools.fitness.services import fitness_service as svc

    logged_at = datetime(2026, 6, 11, 16, 0, 0)
    cm = _mock_cursor(row=(12, "cardio", [{"name": "Run"}], 35, 300, "Tempo", logged_at))

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.update_workout(
            user_id=7,
            workout_id=12,
            updates={
                "workout_type": "cardio",
                "exercises": [{"name": "Run"}],
                "duration_min": 35,
                "ignored": "nope",
            },
        )

    assert result["id"] == 12
    assert result["logged_at"] == "2026-06-11T16:00:00"
    sql, params = cm.cursor.execute.call_args.args
    assert "UPDATE fitness_workout_logs" in sql
    assert "WHERE id = %s AND user_id = %s" in sql
    assert params[-2:] == (12, 7)
    assert "ignored" not in sql


def test_delete_workout_checks_user_id_and_returns_deleted_state():
    from tools.fitness.services import fitness_service as svc

    cm = _mock_cursor(rowcount=1)

    with patch.object(svc, "get_db_cursor", return_value=cm):
        assert svc.delete_workout(user_id=7, workout_id=12) is True

    sql, params = cm.cursor.execute.call_args.args
    assert "DELETE FROM fitness_workout_logs" in sql
    assert "WHERE id = %s AND user_id = %s" in sql
    assert params == (12, 7)


def test_update_goal_checks_user_id_and_returns_updated_row():
    from tools.fitness.services import fitness_service as svc

    created_at = datetime(2026, 6, 10, 9, 0, 0)
    cm = _mock_cursor(row=(9, "weekly workouts", 5, 2, "sessions", None, created_at))

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.update_goal(
            user_id=7,
            goal_id=9,
            updates={"target": 5, "current": 2, "ignored": "nope"},
        )

    assert result == {
        "id": 9,
        "goal_type": "weekly workouts",
        "target": 5.0,
        "current": 2.0,
        "unit": "sessions",
        "deadline": None,
        "created_at": "2026-06-10T09:00:00",
    }
    sql, params = cm.cursor.execute.call_args.args
    assert "UPDATE fitness_goals" in sql
    assert "WHERE id = %s AND user_id = %s" in sql
    assert params[-2:] == (9, 7)
    assert "ignored" not in sql


def test_delete_goal_checks_user_id_and_returns_deleted_state():
    from tools.fitness.services import fitness_service as svc

    cm = _mock_cursor(rowcount=0)

    with patch.object(svc, "get_db_cursor", return_value=cm):
        assert svc.delete_goal(user_id=7, goal_id=9) is False

    sql, params = cm.cursor.execute.call_args.args
    assert "DELETE FROM fitness_goals" in sql
    assert "WHERE id = %s AND user_id = %s" in sql
    assert params == (9, 7)


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


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "weight": 80,
                "height": 180,
                "age": 30,
                "gender": "male",
                "activity_level": "moderate",
                "goal": "maintain",
            },
            {
                "bmr": 1780,
                "tdee": 2759,
                "target_calories": 2759,
                "macros": {"protein": 160, "carbs": 357, "fat": 77},
            },
        ),
        (
            {
                "weight": 50,
                "height": 150,
                "age": 18,
                "gender": "female",
                "activity_level": "sedentary",
                "goal": "lose",
            },
            {
                "bmr": 1186,
                "tdee": 1424,
                "target_calories": 924,
                "macros": {"protein": 100, "carbs": 73, "fat": 26},
            },
        ),
        (
            {
                "weight": 90,
                "height": 190,
                "age": 40,
                "gender": "male",
                "activity_level": "active",
                "goal": "gain",
            },
            {
                "bmr": 1892,
                "tdee": 3265,
                "target_calories": 3565,
                "macros": {"protein": 180, "carbs": 488, "fat": 99},
            },
        ),
    ],
)
def test_calculate_macros_returns_mifflin_st_jeor_estimates(kwargs, expected):
    from tools.fitness.services import fitness_service as svc

    assert svc.calculate_macros(**kwargs) == expected


def test_calculate_macros_uses_default_gender_activity_and_goal():
    from tools.fitness.services import fitness_service as svc

    assert svc.calculate_macros(weight=85, height=175, age=29) == {
        "bmr": 1804,
        "tdee": 2796,
        "target_calories": 2796,
        "macros": {"protein": 170, "carbs": 354, "fat": 78},
    }


def test_calculate_macros_falls_back_to_moderate_multiplier_for_unknown_activity():
    from tools.fitness.services import fitness_service as svc

    assert svc.calculate_macros(
        weight=70,
        height=175,
        age=25,
        gender="male",
        activity_level="extreme",
        goal="maintain",
    ) == {
        "bmr": 1674,
        "tdee": 2594,
        "target_calories": 2594,
        "macros": {"protein": 140, "carbs": 346, "fat": 72},
    }


def test_calculate_macros_treats_unknown_gender_as_female_formula():
    from tools.fitness.services import fitness_service as svc

    assert svc.calculate_macros(
        weight=60,
        height=160,
        age=25,
        gender="other",
        activity_level="sedentary",
        goal="maintain",
    ) == {
        "bmr": 1314,
        "tdee": 1577,
        "target_calories": 1577,
        "macros": {"protein": 120, "carbs": 176, "fat": 44},
    }


def test_calculate_macros_handles_zero_weight():
    from tools.fitness.services import fitness_service as svc

    assert svc.calculate_macros(weight=0, height=180, age=30) == {
        "bmr": 980,
        "tdee": 1519,
        "target_calories": 1519,
        "macros": {"protein": 0, "carbs": 285, "fat": 42},
    }


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "weight": 65,
                "height": 165,
                "age": 28,
                "gender": "female",
                "activity_level": "light",
                "goal": "lose",
            },
            {
                "bmr": 1380,
                "tdee": 1898,
                "target_calories": 1398,
                "macros": {"protein": 130, "carbs": 132, "fat": 39},
            },
        ),
        (
            {
                "weight": 100,
                "height": 185,
                "age": 45,
                "gender": "male",
                "activity_level": "very_active",
                "goal": "gain",
            },
            {
                "bmr": 1936,
                "tdee": 3679,
                "target_calories": 3979,
                "macros": {"protein": 200, "carbs": 546, "fat": 111},
            },
        ),
    ],
)
def test_calculate_macros_covers_remaining_activity_levels(kwargs, expected):
    from tools.fitness.services import fitness_service as svc

    assert svc.calculate_macros(**kwargs) == expected
