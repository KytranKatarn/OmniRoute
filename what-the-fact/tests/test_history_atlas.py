"""Atlas preview: no production app boot, database, inference or network."""

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from flask import Flask

from consumer import history_data
from consumer.history_routes import history_bp

CONSUMER = Path(__file__).resolve().parents[1] / "consumer"


@pytest.fixture
def app():
    history_data.load_catalog.cache_clear()
    app = Flask(__name__, template_folder=str(CONSUMER / "templates"), static_folder=str(CONSUMER / "static"))
    app.secret_key = "atlas-local-test-only"
    app.config.update(TESTING=True, WTF_HISTORY_ATLAS_ENABLED=True)
    app.register_blueprint(history_bp)
    yield app
    history_data.load_catalog.cache_clear()


def test_archive_identity_and_draft_integrity(app):
    data = history_data.load_catalog()
    assert len(data["events"]) == 159
    assert len(data["sources"]) == 128
    assert len(data["movements"]) == 13
    assert len(data["maps"]) == 23
    assert all(e["publication_ready"] is False for e in data["events"])
    assert all(m["route_geometry"] is None for m in data["movements"])
    assert len(data["manifest"]["archive_sha256"]) == 64
    for item in data["maps"]:
        raw = (history_data.MAP_DIR / item["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert hashlib.sha256(raw.rstrip(b"\n")).hexdigest() == item["original_sha256"]
        for node in ET.fromstring(raw).iter():
            assert node.tag.rsplit("}", 1)[-1] in {"svg", "rect", "path", "text", "g", "title", "desc"}
            assert not any(k.lower().startswith("on") or k.rsplit("}", 1)[-1] in {"href", "src"} for k in node.attrib)
            assert not any("url(" in value.lower() or "@import" in value.lower() for value in node.attrib.values())


@pytest.mark.parametrize(
    "path", ["/history", "/history/atlas", "/history/events/CH-0001", "/history/movements", "/api/history/events"]
)
def test_feature_gate_is_fail_closed(app, path):
    app.config["WTF_HISTORY_ATLAS_ENABLED"] = False
    assert app.test_client().get(path).status_code == 404


def test_public_research_pages_and_pagination(app):
    client = app.test_client()
    response = client.get("/history/atlas")
    assert response.status_code == 200
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert b"159 research drafts, not verified findings" in response.data
    assert b"Next page" in response.data
    assert b"Canadian History Atlas" in response.data
    assert b"Migration &amp; movement" in response.data
    assert b"licensing is unresolved" in response.data
    assert client.get("/history/atlas?page=2").status_code == 200
    assert client.get("/history/movements").status_code == 200
    body = client.get("/history/movements").get_data(as_text=True)
    assert "Unknown — not zero" in body and "Routes are unknown" in body


def test_every_event_has_a_renderable_source_detail(app):
    client = app.test_client()
    for event in history_data.load_catalog()["events"]:
        response = client.get("/history/events/" + event["id"])
        assert response.status_code == 200, event["id"]
        assert b"Not publication-ready" in response.data
        assert b"Source evidence" in response.data
    assert client.get("/history/events/CH-9999").status_code == 404


def test_numeric_year_and_undated_semantics(app):
    data = history_data.load_catalog()
    dated = history_data.matching_events(data, year=1867)
    assert dated
    assert all(
        e["start_year"] <= 1867 <= (e["end_year"] if e["end_year"] is not None else e["start_year"]) for e in dated
    )
    undated = history_data.matching_events(data, undated=True)
    assert undated and all(e["start_year"] is None for e in undated)
    assert history_data.frame_for_year(data, 1763) is None
    assert history_data.frame_for_year(data, None) is None
    assert history_data.frame_for_year(data, 1869)["year"] == 1867


def test_search_handles_accents_and_preserves_region_semantics(app):
    data = history_data.load_catalog()
    assert history_data.matching_events(data, query="Québec") == history_data.matching_events(data, query="quebec")
    matches = history_data.matching_events(data, province="Quebec")
    assert matches and all(e["province_context"] == "Quebec" for e in matches)
    regional = history_data.matching_events(data, region="St. Lawrence and Great Lakes")
    assert regional and all("St. Lawrence and Great Lakes" in e["regions"] for e in regional)
    assert history_data.matching_events(data, query="unfindable-exact-phrase") == []


@pytest.mark.parametrize(
    "query", ["year=bad", "year=2101", "page=-1", "page=x", "year=1867&undated=1", "q=" + "x" * 121]
)
def test_invalid_filters_are_bounded(app, query):
    client = app.test_client()
    assert client.get("/history/atlas?" + query).status_code == 400
    assert client.get("/api/history/events?" + query).status_code == 400


def test_api_is_bounded_read_only_and_explicitly_draft(app):
    client = app.test_client()
    first = client.get("/api/history/events").get_json()
    second = client.get("/api/history/events?page=2").get_json()
    assert first["total"] == 159 and first["research_only"] is True
    assert len(first["events"]) == first["page_size"] == 40
    assert not {e["id"] for e in first["events"]} & {e["id"] for e in second["events"]}
    assert client.post("/api/history/events", json={"publication_ready": True}).status_code == 405


def test_catalog_tampering_is_unavailable_not_empty(app, monkeypatch, tmp_path):
    manifest = (history_data.DATA_DIR / "manifest.json").read_bytes()
    (tmp_path / "manifest.json").write_bytes(manifest)
    (tmp_path / "events.json").write_text('{"events": []}')
    monkeypatch.setattr(history_data, "DATA_DIR", tmp_path)
    history_data.load_catalog.cache_clear()
    response = app.test_client().get("/history/atlas")
    assert response.status_code == 503
    assert b"unavailable" in response.data


def test_source_urls_and_output_are_safe(app, monkeypatch):
    assert history_data.safe_source_url("javascript:alert(1)") is None
    assert history_data.safe_source_url("https://user:password@example.com") is None
    assert history_data.safe_source_url("https://example.com/source") == "https://example.com/source"
    data = history_data.load_catalog()
    modified = dict(data)
    modified["events"] = [dict(data["events"][0], title_en='<script>alert("test")</script>')]
    monkeypatch.setattr("consumer.history_routes.load_catalog", lambda: modified)
    html = app.test_client().get("/history/atlas").get_data(as_text=True)
    assert "&lt;script&gt;" in html and '<script>alert("test")</script>' not in html


def test_production_factory_registers_preview_and_gates_navigation(monkeypatch):
    from consumer.app import create_app
    from consumer import db, routes

    monkeypatch.setenv("FLASK_SECRET_KEY", "atlas-app-factory-test-only")
    monkeypatch.setattr(db, "init_billing_table", lambda: None)
    monkeypatch.setattr(routes, "_nav_source_count", lambda: 0)
    for enabled in (False, True):
        monkeypatch.setenv("WTF_HISTORY_ATLAS_ENABLED", "1" if enabled else "0")
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        assert client.get("/history/atlas").status_code == (200 if enabled else 404)
        navigation = client.get("/platforms").get_data(as_text=True)
        assert ('href="/history/atlas"' in navigation) is enabled
