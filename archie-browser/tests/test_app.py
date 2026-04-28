import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app import create_app
    app = create_app(testing=True)
    with app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "skills" in data


def test_submit_task_missing_fields(client):
    resp = client.post("/task", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_get_task_not_found(client):
    resp = client.get("/task/nonexistent-id")
    assert resp.status_code == 404


def test_get_session_status_missing(client):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import session_manager as sm
    sm.get_session_status.return_value = {"status": "missing", "last_used": None}
    resp = client.get("/session/1/linkedin")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "missing"
