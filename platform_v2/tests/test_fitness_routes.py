"""Tests for Fitness route validation and auth behavior."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


@pytest.fixture
def fitness_app():
    """Minimal Flask app with only the fitness blueprint mounted."""
    mini_app = Flask(__name__, template_folder=str(PLATFORM_ROOT / "templates"))
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["WTF_CSRF_ENABLED"] = False

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    from tools.fitness import fitness_bp

    mini_app.register_blueprint(fitness_bp)
    return mini_app


@pytest.fixture
def fitness_client(fitness_app):
    with fitness_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield client


def test_log_workout_accepts_valid_payload(fitness_client):
    with patch(
        "tools.fitness.routes.svc_log_workout",
        return_value={"id": 99, "logged_at": "2026-06-11T14:30:00"},
    ) as log_workout:
        resp = fitness_client.post(
            "/tools/fitness/api/workout/log",
            json={
                "user_id": 7,
                "workout_type": "cardio",
                "duration_min": 30,
                "exercises": [{"name": "Run"}],
                "calories": 250,
                "notes": "Easy pace",
            },
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["id"] == 99
    log_workout.assert_called_once_with(
        7,
        "cardio",
        [{"name": "Run"}],
        30,
        250,
        "Easy pace",
    )


def test_log_workout_rejects_zero_duration_before_service_call(fitness_client):
    with patch("tools.fitness.routes.svc_log_workout") as log_workout:
        resp = fitness_client.post(
            "/tools/fitness/api/workout/log",
            json={"workout_type": "mobility", "duration_min": 0},
        )

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "Duration" in data["error"]
    log_workout.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"target": 4, "unit": "sessions"},
        {"goal_type": "weekly workouts", "unit": "sessions"},
    ],
)
def test_create_goal_rejects_missing_required_fields(fitness_client, payload):
    with patch("tools.fitness.routes.set_goal") as set_goal:
        resp = fitness_client.post("/tools/fitness/api/goals", json=payload)

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "goal_type and target" in data["error"]
    set_goal.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "expected"),
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
    ],
)
def test_calculate_macros_boundary_values(fitness_client, payload, expected):
    resp = fitness_client.post("/tools/fitness/api/nutrition/macros", json=payload)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    for key, value in expected.items():
        assert data[key] == value


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("weight", 19, "Weight must be between 20 and 400kg"),
        ("height", 99, "Height must be between 100 and 250cm"),
        ("age", 9, "Age must be between 10 and 120"),
    ],
)
def test_calculate_macros_rejects_out_of_range_inputs(
    fitness_client,
    field,
    value,
    expected_error,
):
    payload = {
        "weight": 80,
        "height": 180,
        "age": 30,
        "gender": "male",
        "activity_level": "moderate",
        "goal": "maintain",
    }
    payload[field] = value

    resp = fitness_client.post("/tools/fitness/api/nutrition/macros", json=payload)

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": expected_error}


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("gender", "nonbinary", "Gender must be one of: male, female"),
        (
            "activity_level",
            "extreme",
            "Activity level must be one of: sedentary, light, moderate, active, very_active",
        ),
        ("goal", "bulk", "Goal must be one of: lose, maintain, gain"),
    ],
)
def test_calculate_macros_rejects_unknown_enum_inputs(
    fitness_client,
    field,
    value,
    expected_error,
):
    payload = {
        "weight": 80,
        "height": 180,
        "age": 30,
        "gender": "male",
        "activity_level": "moderate",
        "goal": "maintain",
    }
    payload[field] = value

    resp = fitness_client.post("/tools/fitness/api/nutrition/macros", json=payload)

    assert resp.status_code == 400
    data = resp.get_json()
    assert data == {"success": False, "error": expected_error}


def test_calculate_macros_rejects_non_numeric_required_inputs(fitness_client):
    resp = fitness_client.post(
        "/tools/fitness/api/nutrition/macros",
        json={
            "weight": "eighty",
            "height": 180,
            "age": 30,
            "activity_level": "moderate",
            "goal": "maintain",
        },
    )

    assert resp.status_code == 400
    assert resp.get_json() == {
        "success": False,
        "error": "Weight, height, and age must be numeric",
    }


def test_workout_history_requires_authentication(fitness_app):
    with fitness_app.test_client() as client, patch("tools.fitness.routes.get_workout_history") as history:
        resp = client.get("/tools/fitness/api/workout/history")

    assert resp.status_code == 401
    history.assert_not_called()


def test_workout_history_returns_history_for_authenticated_user(fitness_client):
    expected_history = [{"id": 1, "workout_type": "strength"}]

    with patch(
        "tools.fitness.routes.get_workout_history",
        return_value=expected_history,
    ) as history:
        resp = fitness_client.get("/tools/fitness/api/workout/history?user_id=7&limit=5")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"success": True, "history": expected_history}
    history.assert_called_once_with(7, limit=5)


def test_update_workout_uses_authenticated_user_for_authorization(fitness_client):
    expected_workout = {"id": 12, "workout_type": "cardio"}

    with patch(
        "tools.fitness.routes.svc_update_workout",
        return_value=expected_workout,
    ) as update_workout:
        resp = fitness_client.put(
            "/tools/fitness/api/workout/12",
            json={"user_id": 999, "workout_type": "cardio"},
        )

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "workout": expected_workout}
    update_workout.assert_called_once_with(1, 12, {"user_id": 999, "workout_type": "cardio"})


def test_update_workout_returns_404_when_not_owned_or_missing(fitness_client):
    with patch("tools.fitness.routes.svc_update_workout", return_value=None):
        resp = fitness_client.put("/tools/fitness/api/workout/12", json={"notes": "Updated"})

    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


def test_delete_workout_uses_authenticated_user_for_authorization(fitness_client):
    with patch("tools.fitness.routes.svc_delete_workout", return_value=True) as delete_workout:
        resp = fitness_client.delete("/tools/fitness/api/workout/12")

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "deleted": True}
    delete_workout.assert_called_once_with(1, 12)


def test_delete_workout_returns_404_when_not_owned_or_missing(fitness_client):
    with patch("tools.fitness.routes.svc_delete_workout", return_value=False):
        resp = fitness_client.delete("/tools/fitness/api/workout/12")

    assert resp.status_code == 404
    assert resp.get_json() == {"success": False, "error": "Workout not found"}


def test_update_goal_uses_authenticated_user_for_authorization(fitness_client):
    expected_goal = {"id": 9, "goal_type": "weekly workouts"}

    with patch(
        "tools.fitness.routes.svc_update_goal",
        return_value=expected_goal,
    ) as update_goal:
        resp = fitness_client.put(
            "/tools/fitness/api/goals/9",
            json={"user_id": 999, "target": 5},
        )

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "goal": expected_goal}
    update_goal.assert_called_once_with(1, 9, {"user_id": 999, "target": 5})


def test_update_goal_returns_404_when_not_owned_or_missing(fitness_client):
    with patch("tools.fitness.routes.svc_update_goal", return_value=None):
        resp = fitness_client.put("/tools/fitness/api/goals/9", json={"target": 5})

    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


def test_delete_goal_uses_authenticated_user_for_authorization(fitness_client):
    with patch("tools.fitness.routes.svc_delete_goal", return_value=True) as delete_goal:
        resp = fitness_client.delete("/tools/fitness/api/goals/9")

    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "deleted": True}
    delete_goal.assert_called_once_with(1, 9)


def test_delete_goal_returns_404_when_not_owned_or_missing(fitness_client):
    with patch("tools.fitness.routes.svc_delete_goal", return_value=False):
        resp = fitness_client.delete("/tools/fitness/api/goals/9")

    assert resp.status_code == 404
    assert resp.get_json() == {"success": False, "error": "Goal not found"}


def test_available_models_returns_default_dhq_option(fitness_client):
    """The selector must not depend on an uninitialized dispatcher object."""
    resp = fitness_client.get("/tools/fitness/api/models")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "success": True,
        "models": [{"name": "default", "size": 0, "modified": ""}],
    }
