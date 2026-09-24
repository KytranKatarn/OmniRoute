"""Tests for Therapy mood validation, encouragement, and stats aggregation."""

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
def therapy_client():
    """Minimal Flask client with only the Therapy blueprint mounted."""
    mini_app = Flask(__name__, template_folder=str(PLATFORM_ROOT / "templates"))
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    from tools.therapy import therapy_bp

    mini_app.register_blueprint(therapy_bp)

    with mini_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield client


@pytest.mark.parametrize("mood_score", [None, 0, 11, "5", 4.5])
def test_log_mood_rejects_scores_outside_integer_1_to_10(therapy_client, mood_score):
    payload = {}
    if mood_score is not None:
        payload["mood_score"] = mood_score

    with patch("tools.therapy.routes.svc_log_mood") as svc_log_mood:
        resp = therapy_client.post("/tools/therapy/api/mood", json=payload)

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "between 1 and 10" in data["error"]
    svc_log_mood.assert_not_called()


@pytest.mark.parametrize("mood_score", [1, 10])
def test_log_mood_accepts_boundary_scores_1_and_10(therapy_client, mood_score):
    with patch(
        "tools.therapy.routes.svc_log_mood",
        return_value={"id": 123, "logged_at": "2026-06-11T12:00:00"},
    ) as svc_log_mood:
        resp = therapy_client.post("/tools/therapy/api/mood", json={"mood_score": mood_score})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["mood_score"] == mood_score
    svc_log_mood.assert_called_once_with(1, mood_score, None, "", [])


@pytest.mark.parametrize(
    ("mood", "expected_snippet"),
    [
        (3, "difficult days"),
        (4, "middle ground"),
        (5, "middle ground"),
        (6, "doing well"),
        (7, "doing well"),
        (8, "Wonderful"),
        (10, "Wonderful"),
    ],
)
def test_get_mood_encouragement_maps_expected_tiers(mood, expected_snippet):
    from tools.therapy.routes import get_mood_encouragement

    assert expected_snippet in get_mood_encouragement(mood)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self.rows.pop(0)


class _FakeDbCursor:
    def __init__(self, rows):
        self.cursor = _FakeCursor(rows)

    def __enter__(self):
        return None, self.cursor

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.parametrize(
    ("recent_avg", "prior_avg", "expected_trend"),
    [
        (7.0, 6.0, "improving"),
        (5.0, 6.0, "declining"),
        (6.4, 6.0, "stable"),
    ],
)
def test_get_therapy_stats_aggregates_avg_mood_and_trend(recent_avg, prior_avg, expected_trend):
    from tools.therapy.services import therapy_service

    rows = [
        (6.245, 4),
        (2,),
        (recent_avg, prior_avg),
    ]
    with patch("tools.therapy.services.therapy_service.get_db_cursor", return_value=_FakeDbCursor(rows)):
        stats = therapy_service.get_therapy_stats(user_id=1)

    assert stats["avg_mood_7d"] == 6.25
    assert stats["mood_entries_7d"] == 4
    assert stats["sessions_this_month"] == 2
    assert stats["mood_trend"] == expected_trend


def test_log_mood_rejects_mismatched_user_id(therapy_client):
    with patch("tools.therapy.routes.svc_log_mood") as svc_log_mood:
        resp = therapy_client.post(
            "/tools/therapy/api/mood",
            json={"mood_score": 5, "user_id": 2},
        )

    assert resp.status_code == 403
    svc_log_mood.assert_not_called()


def test_chat_dispatches_for_authenticated_user_locally(therapy_client):
    with patch("tools.therapy.routes.get_ai_context", return_value=""), patch(
        "tools.therapy.routes.dispatch_json",
        return_value={"response": "I hear you.", "model_used": "dhq"},
    ) as dispatch_json:
        resp = therapy_client.post("/tools/therapy/api/chat", json={"message": "I am stressed"})

    assert resp.status_code == 200
    assert dispatch_json.call_args.kwargs["user_id"] == 1
    assert dispatch_json.call_args.kwargs["local_only"] is True
