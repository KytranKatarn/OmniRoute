from datetime import datetime
import pytest
from sqlalchemy import text
from tech.app import create_app
from ingest.persist import upsert_article


@pytest.fixture()
def client(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("KYTRAN_CLIENT_ID", "wtf-tech")
    monkeypatch.setenv("KYTRAN_CLIENT_SECRET", "s")
    monkeypatch.setenv("KYTRAN_AUTH_URL", "https://platform.kytranempowerment.com")
    monkeypatch.setenv("KYTRAN_REDIRECT_URI", "https://what-the-fact.tech/auth/kytran/callback")
    import tech.api
    tech.api._engine = None
    with engine.begin() as c:
        c.execute(text("INSERT INTO wtf_test.sources (slug, name, url) VALUES ('t','T','http://x')"))
        sid = c.execute(text("SELECT id FROM wtf_test.sources WHERE slug='t'")).scalar()
    upsert_article(engine, sid,
        {"external_id": "g-1", "title": "API test", "body": "b",
         "url": "http://x/1", "published_at": datetime(2026, 4, 18)},
        {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "none"})
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_api_list_shape(client):
    r = client.get("/api/v1/articles?limit=50")
    assert r.status_code == 200
    data = r.get_json()
    assert "articles" in data and isinstance(data["articles"], list)
    a = data["articles"][0]
    assert set(a.keys()) >= {"id", "title", "url", "published_at", "source", "bias"}


def test_api_detail_shape(client):
    r = client.get("/api/v1/articles/1")
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == 1
    assert "bias" in data and "band" in data["bias"]


def test_api_audit_shape(client):
    r = client.get("/api/v1/articles/1/audit")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data["events"], list) and len(data["events"]) >= 1


def test_api_404(client):
    r = client.get("/api/v1/articles/999999")
    assert r.status_code == 404
