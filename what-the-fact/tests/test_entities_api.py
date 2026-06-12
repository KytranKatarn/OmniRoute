import pytest
from consumer.app import create_app


@pytest.fixture()
def client(entity_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("WTF_SHARED_SCHEMA", "shared_test")
    monkeypatch.setenv("WTF_PARLIAMENT_SCHEMA", "parliament_test")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    import consumer.entities as ent
    ent._engine = None  # rebind to the test DB URL
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def paid_client(client):
    """Same client with an authenticated paid session so gated endpoints pass."""
    with client.session_transaction() as sess:
        sess["wtf_authenticated"] = True
        sess["wtf_tier"] = "pro"
    return client


# --- search ---------------------------------------------------------------

def test_search_mp_by_name(client, entity_schema):
    r = client.get("/api/entities/search?q=jane&type=mp")
    assert r.status_code == 200
    body = r.get_json()
    assert "coverage_pct" in body
    hits = body["results"]
    jane = next(h for h in hits if h["slug"] == "jane-member")
    assert jane["type"] == "mp"
    assert jane["article_count"] == 2


def test_search_journalist_returns_entity_with_zero_articles(client, entity_schema):
    r = client.get("/api/entities/search?q=bob&type=journalist")
    assert r.status_code == 200
    hits = r.get_json()["results"]
    bob = next((h for h in hits if h["slug"] == "bob-writer"), None)
    assert bob is not None, "bob-writer entity not found in results"
    assert bob["type"] == "journalist"
    assert bob["article_count"] == 0


def test_search_journalist_does_not_return_mp(client):
    r = client.get("/api/entities/search?q=jane&type=journalist")
    assert r.status_code == 200
    assert all(h["slug"] != "jane-member" for h in r.get_json()["results"])


def test_search_rejects_invalid_type(client):
    r = client.get("/api/entities/search?q=x&type=senator")
    assert r.status_code == 400


# --- coverage (subscriber-gated) ------------------------------------------

def test_coverage_counts_trend_and_bias(paid_client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    r = paid_client.get(f"/api/entities/{eid}/coverage")
    assert r.status_code == 200
    b = r.get_json()
    assert b["article_count"] == 2
    assert b["bias_distribution"]["left"] == 1
    assert b["bias_distribution"]["center"] == 1
    assert isinstance(b["trend"], list) and b["trend"]
    assert any(o["slug"] == "src" for o in b["top_outlets"])
    assert "coverage_pct" in b


def test_coverage_unknown_entity_404(paid_client):
    r = paid_client.get("/api/entities/999999/coverage")
    assert r.status_code == 404


def test_coverage_unauthenticated_redirects_to_login(client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    r = client.get(f"/api/entities/{eid}/coverage")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_coverage_free_tier_402(client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    with client.session_transaction() as sess:
        sess["wtf_authenticated"] = True
        sess["wtf_tier"] = "free"
    r = client.get(f"/api/entities/{eid}/coverage")
    assert r.status_code == 402
    assert r.get_json()["error"] == "subscription_required"


# --- accountability (subscriber-gated) ------------------------------------

def test_accountability_for_mp(paid_client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    r = paid_client.get(f"/api/entities/{eid}/accountability")
    assert r.status_code == 200
    b = r.get_json()
    assert b["mp"]["name"] == "Jane Member"
    assert b["expense_summary"]["total_cents"] == 123456
    assert any(v["bill_number"] == "C-1" for v in b["recent_votes"])
    assert any(p["text"] == "Lower taxes" for p in b["promises"])


def test_accountability_404_for_journalist(paid_client, entity_schema):
    eid = entity_schema["journalist_entity_id"]
    r = paid_client.get(f"/api/entities/{eid}/accountability")
    assert r.status_code == 404


def test_accountability_unauthenticated_redirects_to_login(client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    r = client.get(f"/api/entities/{eid}/accountability")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]
