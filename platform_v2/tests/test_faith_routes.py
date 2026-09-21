"""Tests for the Faith module reader, search, and status routes (Project #284).

Uses a minimal Flask test client — the full ARCHIE app cannot be imported
in tests because oauth_routes.py does `from app import User` and
/app/__init__.py (package init) shadows app.py (known pre-existing issue,
documented in test_approvals_multi_source.py). The LLM-facing care routes
(chat, practices, check-ins, journal, chaplain) have their own file,
test_faith_care_routes.py, with the same client/stub block.

Run: docker exec archie_platform python -m pytest tests/test_faith_routes.py -v
"""

from __future__ import annotations

import types

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

from tests.modstub import stub_module_scoped


@pytest.fixture(autouse=True, scope="module")
def _stub_department_dispatcher():
    """Stub the DHQ dispatcher for this module (#272154).

    routes.py imports `dispatch` at module import time, and the real module
    pulls `from db import _get_db_password` from a module that is not
    importable under the coder-lane pytest invocation (--noconftest). Every
    LLM-facing test here mocks archie_bridge, so the stub is never invoked.
    """
    stub = types.ModuleType("tools.department_hq.services.department_dispatcher")
    stub.dispatch = lambda *args, **kwargs: {"success": False, "response": "(dispatcher stubbed)"}
    stub.__file__ = __file__
    stub.__package__ = "tools.department_hq.services"
    with stub_module_scoped("tools.department_hq.services.department_dispatcher", stub):
        yield stub


@pytest.fixture(scope="module")
def faith_client():
    """Minimal Flask test client with only the faith blueprint mounted."""
    mini_app = Flask(__name__, template_folder="/app/templates")
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

    from tools.faith import faith_bp

    mini_app.register_blueprint(faith_bp)

    return mini_app.test_client()


def _login(client):
    """Inject a Flask-Login session for user 1."""
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True


def test_faith_blueprint_registered(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/")
    assert resp.status_code in (200, 302), f"Got {resp.status_code}"


def test_faith_status_endpoint(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agent_id"] == 352


def test_faith_bible_meta(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/bible/meta")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["translation"]["id"] == "web"
    assert data["translation"]["verse_count"] > 30000
    assert any(book["code"] == "JOH" for book in data["books"])


def test_faith_bible_passage(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/bible/passage?book=John&chapter=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["book"] == "JOH"
    assert any(verse["verse"] == 16 for verse in data["verses"])


def test_faith_bible_search(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/bible/search?q=God%20so%20loved")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert any(result["reference"] == "John 3:16" for result in data["results"])


def test_faith_bible_search_clamps_user_limit(faith_client):
    from unittest.mock import patch

    verses = [
        {"reference": f"Test {i}", "text": "mercy", "book": "TST", "chapter": 1, "verse": i} for i in range(1, 151)
    ]
    _login(faith_client)
    with patch("tools.faith.routes._load_web_bible", return_value={"verses": verses}):
        resp = faith_client.get("/tools/faith/api/faith/bible/search?q=mercy&limit=100000")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 100
    assert len(data["results"]) == 100


def test_faith_scriptures_search_clamps_user_limit(faith_client):
    from unittest.mock import patch

    passages = [
        {"collection": "web", "reference": f"Test {i}", "text": "peace", "_search": "peace"} for i in range(1, 151)
    ]
    _login(faith_client)
    with patch("tools.faith.routes._load_scripture_corpus", return_value={"passages": passages}):
        resp = faith_client.get("/tools/faith/api/faith/scriptures/search?q=peace&limit=100000")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 100
    assert len(data["results"]) == 100


def test_faith_encyclopedia_search(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/encyclopedia/search?q=fathers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert any("Fathers" in entry["title"] for entry in data["entries"])


def test_faith_encyclopedia_search_clamps_user_limit(faith_client):
    from unittest.mock import patch

    entries = [
        {"title": f"Faith Entry {i}", "category": "test", "summary": "wisdom", "tags": ["wisdom"]}
        for i in range(1, 151)
    ]
    _login(faith_client)
    with patch("tools.faith.routes._load_encyclopedia_entries", return_value=entries):
        resp = faith_client.get("/tools/faith/api/faith/encyclopedia/search?q=wisdom&limit=100000")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 100
    assert len(data["entries"]) == 100


@pytest.mark.parametrize(
    ("path", "result_key"),
    [
        ("/tools/faith/api/faith/bible/search?q=mercy&limit=0", "results"),
        ("/tools/faith/api/faith/scriptures/search?q=mercy&limit=0", "results"),
        ("/tools/faith/api/faith/encyclopedia/search?q=mercy&limit=0", "entries"),
    ],
)
def test_faith_search_limits_clamp_to_minimum(faith_client, path, result_key):
    from unittest.mock import patch

    verses = [{"reference": f"Test {i}", "text": "mercy", "book": "TST", "chapter": 1, "verse": i} for i in range(1, 3)]
    passages = [
        {"collection": "web", "reference": f"Test {i}", "text": "mercy", "_search": "mercy"} for i in range(1, 3)
    ]
    entries = [{"title": f"Mercy {i}", "category": "test", "summary": "mercy", "tags": ["mercy"]} for i in range(1, 3)]
    _login(faith_client)
    with patch("tools.faith.routes._load_web_bible", return_value={"verses": verses}), patch(
        "tools.faith.routes._load_scripture_corpus", return_value={"passages": passages}
    ), patch("tools.faith.routes._load_encyclopedia_entries", return_value=entries):
        resp = faith_client.get(path)

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert len(data[result_key]) == 1


def test_encyclopedia_search_empty_query_returns_unfiltered_entries(faith_client):
    from unittest.mock import patch

    entries = [
        {"title": "Desert Fathers", "category": "history", "summary": "Early monastics", "tags": ["monastic"]},
        {"title": "Lectio Divina", "category": "practice", "summary": "Sacred reading", "tags": ["prayer"]},
    ]
    _login(faith_client)
    with patch("tools.faith.routes._load_encyclopedia_entries", return_value=entries):
        resp = faith_client.get("/tools/faith/api/faith/encyclopedia/search?q=")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["query"] == ""
    assert data["count"] == 2
    assert data["entries"] == entries


def test_encyclopedia_search_accepts_query_over_500_chars(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    long_query = "x" * 501
    entries = [{"title": "Mercy", "category": "virtue", "summary": "Compassion", "tags": ["mercy"]}]
    with patch("tools.faith.routes._load_encyclopedia_entries", return_value=entries):
        resp = faith_client.get(f"/tools/faith/api/faith/encyclopedia/search?q={long_query}")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["query"] == long_query
    assert data["count"] == 0
    assert data["entries"] == []


def test_scriptures_meta_reader_toc_covers_all_collections(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/meta")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    toc = data["toc"]
    expected_collections = {
        "web",
        "jps1917",
        "quran_rodwell",
        "dhammapada_muller",
        "bhagavad_gita_arnold",
        "tao_legge",
        "analects_legge",
    }
    assert set(toc.keys()) == expected_collections
    genesis = next((book for book in toc["web"]["books"] if book["key"] == "Genesis"), None)
    assert genesis is not None
    assert genesis["chapters"]
    assert genesis["chapters"][0]["count"] > 0


def test_scriptures_passage_reads_bible_chapter(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=web&book=Genesis&chapter=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0
    assert any(passage.get("verse") == 16 for passage in data["passages"])
    assert all(passage["collection"] == "web" for passage in data["passages"])


def test_scriptures_passage_reads_tanakh_chapter(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=jps1917&book=Genesis&chapter=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0
    assert all(passage["reference"] and passage["text"] for passage in data["passages"])


def test_scriptures_passage_reads_quran_sura(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=quran_rodwell&chapter=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0
    assert "Sura 1" in data["chapter"]


def test_scriptures_passage_reads_dhammapada_chapter(faith_client):
    _login(faith_client)
    resp = faith_client.get(
        "/tools/faith/api/faith/scriptures/passage?collection=dhammapada_muller"
        "&chapter=Chapter%20I.%20The%20Twin-Verses"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0


def test_scriptures_passage_reads_gita_chapter(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=bhagavad_gita_arnold&chapter=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0


def test_scriptures_passage_reads_analects_book(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=analects_legge&book=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0


def test_scriptures_passage_reads_tao_chapter(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=tao_legge&chapter=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] > 0


def test_scriptures_passage_rejects_unknown_collection(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=apocrypha&book=X&chapter=1")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "unknown collection"


def test_scriptures_passage_rejects_unknown_chapter(faith_client):
    _login(faith_client)
    resp = faith_client.get("/tools/faith/api/faith/scriptures/passage?collection=web&book=Genesis&chapter=999")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "unknown chapter for book"


def test_tao_loader_splits_multiple_chapters():
    from tools.faith.routes import _load_tao_legge, _reader_units

    tao_records = _load_tao_legge()
    references = [record["reference"] for record in tao_records]
    assert "Tao Teh King Chapter 2" in references
    assert len(set(references)) > 1
    tao_chapters = {
        unit["chapter"] for unit in _reader_units() if unit["collection"] == "tao_legge" and unit["chapter"] is not None
    }
    assert len(tao_chapters) > 1
