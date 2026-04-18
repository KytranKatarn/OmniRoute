import os
from datetime import datetime
import pytest
from sqlalchemy import text

from consumer.app import create_app
from ingest.persist import upsert_article


@pytest.fixture()
def app(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    # Reset engine singleton so it picks up WTF_DATABASE_URL
    import consumer.routes
    consumer.routes._engine = None
    # seed a source + article
    with engine.begin() as c:
        c.execute(text("INSERT INTO wtf_test.sources (slug, name, url) VALUES ('t', 'T', 'http://x')"))
        sid = c.execute(text("SELECT id FROM wtf_test.sources WHERE slug='t'")).scalar()
    upsert_article(engine, sid,
        {"external_id": "g-1", "title": "Headline one", "body": "body",
         "url": "http://x/1", "published_at": datetime(2026, 4, 18)},
        {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "none"})
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_index_lists_article(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Headline one" in r.data
    assert b"center" in r.data  # bias band badge


def test_detail_renders(client):
    r = client.get("/article/1")
    assert r.status_code == 200
    assert b"Headline one" in r.data
    assert b"body" in r.data


def test_detail_404(client):
    r = client.get("/article/999999")
    assert r.status_code == 404
