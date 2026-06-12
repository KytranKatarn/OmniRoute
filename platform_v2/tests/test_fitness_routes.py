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
        ("weight", 29, "Weight must be between 30 and 300kg"),
        ("weight", 301, "Weight must be between 30 and 300kg"),
        ("height", 99, "Height must be between 100 and 250cm"),
        ("height", 251, "Height must be between 100 and 250cm"),
        ("age", 9, "Age must be between 10 and 120"),
        ("age", 121, "Age must be between 10 and 120"),
        (
            "activity_level",
            "extreme",
            "Activity level must be one of: sedentary, light, moderate, active, very_active",
        ),
        ("goal", "bulk", "Goal must be one of: lose, maintain, gain"),
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
