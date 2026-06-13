"""Tests for DOC medical safety response guards."""

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
def doc_client():
    """Minimal Flask client with only the DOC blueprint mounted."""
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

    from tools.doc import doc_bp

    mini_app.register_blueprint(doc_bp)

    with mini_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield client


def test_doc_chat_always_includes_healthcare_disclaimer(doc_client):
    from tools.doc.routes import MEDICAL_DISCLAIMER

    with patch("tools.doc.routes.get_ai_context", return_value=""), patch(
        "tools.doc.routes.dispatch_json",
        return_value={"response": "Hydration and rest can help with many minor headaches.", "model_used": "dhq"},
    ):
        resp = doc_client.post("/tools/doc/api/chat", json={"message": "I have a mild headache."})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "consult a healthcare professional" in data["response"].lower()
    assert MEDICAL_DISCLAIMER in data["response"]


def test_doc_symptom_analysis_always_includes_healthcare_disclaimer(doc_client):
    from tools.doc.routes import MEDICAL_DISCLAIMER

    with patch("tools.doc.routes.svc_log_symptoms"), patch(
        "tools.doc.routes.dispatch_json",
        return_value={"response": "Track timing, severity, and any changes in symptoms."},
    ):
        resp = doc_client.post(
            "/tools/doc/api/symptoms",
            json={"symptoms": "fatigue", "severity": 3, "duration": "two days"},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "consult a healthcare professional" in data["analysis"].lower()
    assert MEDICAL_DISCLAIMER in data["analysis"]


@pytest.mark.parametrize("keyword", ["chest pain", "stroke", "heart attack"])
def test_doc_chat_emergency_keywords_append_call_911(doc_client, keyword):
    from tools.doc.routes import EMERGENCY_APPENDIX, MEDICAL_DISCLAIMER

    with patch("tools.doc.routes.get_ai_context", return_value=""), patch(
        "tools.doc.routes.dispatch_json",
        return_value={"response": "These symptoms can be concerning.", "model_used": "dhq"},
    ):
        resp = doc_client.post(
            "/tools/doc/api/chat",
            json={"message": f"I am worried about {keyword}."},
        )

    assert resp.status_code == 200
    response = resp.get_json()["response"].lower()
    assert "consult a healthcare professional" in response
    assert "call 911" in response
    assert MEDICAL_DISCLAIMER in resp.get_json()["response"]
    assert EMERGENCY_APPENDIX in resp.get_json()["response"]


@pytest.mark.parametrize("keyword", ["chest pain", "stroke", "heart attack"])
def test_doc_symptom_analysis_emergency_keywords_append_call_911(doc_client, keyword):
    from tools.doc.routes import EMERGENCY_APPENDIX, MEDICAL_DISCLAIMER

    with patch("tools.doc.routes.svc_log_symptoms"), patch(
        "tools.doc.routes.dispatch_json",
        return_value={"response": "Seek urgent evaluation for severe or worsening symptoms."},
    ):
        resp = doc_client.post(
            "/tools/doc/api/symptoms",
            json={"symptoms": keyword, "severity": 8, "duration": "today"},
        )

    assert resp.status_code == 200
    analysis = resp.get_json()["analysis"].lower()
    assert "consult a healthcare professional" in analysis
    assert "call 911" in analysis
    assert MEDICAL_DISCLAIMER in resp.get_json()["analysis"]
    assert EMERGENCY_APPENDIX in resp.get_json()["analysis"]
