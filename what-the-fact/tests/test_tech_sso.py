import pytest
from tech.app import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("KYTRAN_CLIENT_ID", "wtf-tech")
    monkeypatch.setenv("KYTRAN_CLIENT_SECRET", "s")
    monkeypatch.setenv("KYTRAN_AUTH_URL", "https://platform.kytranempowerment.com")
    monkeypatch.setenv("KYTRAN_REDIRECT_URI", "https://what-the-fact.tech/auth/kytran/callback")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index_public(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"radical transparency" in r.data.lower() or b"transparent" in r.data.lower()


def test_dashboard_requires_sso(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 301)
    assert "/auth/kytran/login" in r.location


def test_login_redirects_to_oauth(client):
    r = client.get("/auth/kytran/login", follow_redirects=False)
    assert r.status_code == 302
    assert "platform.kytranempowerment.com" in r.location
    assert "client_id=wtf-tech" in r.location
