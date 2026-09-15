"""Tests for the Faith module (Project #284).

Uses a minimal Flask test client — the full ARCHIE app cannot be imported
in tests because oauth_routes.py does `from app import User` and
/app/__init__.py (package init) shadows app.py (known pre-existing issue,
documented in test_approvals_multi_source.py).

Run: docker exec archie_platform python -m pytest tests/test_faith_routes.py -v
"""

from __future__ import annotations

import types

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

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


@contextmanager
def _patched_db():
    """Patch `get_db_cursor` with a mock of the RIGHT SHAPE (#6015).

    Production does `with get_db_cursor(commit=True) as (_conn, cur):` — the context
    manager yields a (connection, cursor) PAIR. A bare `patch("...get_db_cursor")` hands
    back a plain MagicMock whose `__enter__` yields an *empty iterator*, so that unpack
    raises `ValueError: not enough values to unpack (expected 2, got 0)` INSIDE the route.

    That surfaces as an HTTP 500 and reads exactly like a production defect — it was the
    only 500-family in the whole suite, and the reason #6015 existed. The code under test
    is correct; the mock was the wrong shape.
    """
    with patch("tools.faith.routes.get_db_cursor") as m:
        m.return_value.__enter__.return_value = (MagicMock(), MagicMock())
        yield m


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


def _logout(client):
    """Clear Flask-Login session state for auth-gate assertions."""
    with client.session_transaction() as sess:
        sess.clear()


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


def test_faith_chat_returns_response(faith_client):
    from unittest.mock import patch

    mock_result = {
        "success": True,
        "response": "Peace I leave with you.\n\n---\n**From the Chaplain**\nFaith walks in the dark.",
        "model_used": "mistral:7b",
        "agent": "F.A.I.T.H.",
    }
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock_result), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.post(
            "/tools/faith/api/faith/chat",
            json={"message": "What does scripture say about doubt?"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_chat_crisis_detection(faith_client):
    from unittest.mock import patch

    mock_result = {"success": True, "response": "...", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock_result), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.post(
            "/tools/faith/api/faith/chat",
            json={"message": "I have no reason to live"},
        )
    assert resp.status_code == 200
    assert resp.get_json().get("crisis_detected") is True


def test_faith_devotional(faith_client):
    from unittest.mock import patch

    mock = {"success": True, "response": "John 14:27", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.get("/tools/faith/api/faith/devotional")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_scripture_search(faith_client):
    from unittest.mock import patch

    mock = {"success": True, "response": "Psalm 34:18", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", return_value=mock), patch(
        "tools.faith.routes.BRIDGE_AVAILABLE", True
    ), _patched_db():
        resp = faith_client.post("/tools/faith/api/faith/scripture-search", json={"query": "grief"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_scripture_search_uses_profile_tradition(faith_client):
    from unittest.mock import patch

    captured = {}

    def fake_bridge(prompt, system_prompt):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return {"success": True, "response": "Qur'an reference", "model_used": "dhq", "agent": "F.A.I.T.H."}

    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", side_effect=fake_bridge), patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "muslim", "prayer_style": "guided", "scripture_translation": "web"},
    ):
        resp = faith_client.post("/tools/faith/api/faith/scripture-search", json={"query": "mercy"})

    assert resp.status_code == 200
    assert "Muslim user" in captured["prompt"]
    assert "Tradition preference: Muslim" in captured["system_prompt"]


def test_faith_devotional_uses_multi_tradition_reflection_prompt(faith_client):
    from unittest.mock import patch

    captured = {}

    def fake_bridge(prompt, system_prompt):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return {"success": True, "response": "A Dhammapada reflection", "model_used": "dhq", "agent": "F.A.I.T.H."}

    _login(faith_client)
    with patch("tools.faith.routes.archie_bridge", side_effect=fake_bridge), patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "buddhist", "prayer_style": "meditation", "scripture_translation": "web"},
    ):
        resp = faith_client.get("/tools/faith/api/faith/devotional")

    assert resp.status_code == 200
    assert "daily spiritual reflection" in captured["prompt"]
    assert "Buddhist user" in captured["prompt"]
    assert "Prayer/meditation style: meditation" in captured["system_prompt"]


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


def test_faith_checkin_saves(faith_client):
    from unittest.mock import MagicMock, patch

    _login(faith_client)
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"id": 1}
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("tools.faith.routes.get_db_cursor", return_value=mock_ctx):
        resp = faith_client.post(
            "/tools/faith/api/faith/checkin",
            json={"score": 4, "reflection": "Feeling close to God."},
        )
    assert resp.status_code == 201


def test_faith_journal_list(faith_client):
    from unittest.mock import MagicMock, patch

    _login(faith_client)
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("tools.faith.routes.get_db_cursor", return_value=mock_ctx):
        resp = faith_client.get("/tools/faith/api/faith/journal")
    assert resp.status_code == 200
    assert "entries" in resp.get_json()


def test_connect_chaplain(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._send_chaplain_email", return_value=True), _patched_db():
        resp = faith_client.post(
            "/tools/faith/api/faith/connect-chaplain",
            json={"message": "I need to talk."},
        )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"prayer_type": ""},
        {"prayer_type": "prosperity"},
        {"type": "general", "intention": "x" * 501},
    ],
)
def test_guided_prayer_rejects_invalid_payload_before_dispatch(faith_client, payload):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post("/tools/faith/api/faith/prayer", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    practice_dispatch.assert_not_called()


def test_guided_prayer_accepts_valid_prayer_type_field(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "christian", "prayer_style": "guided"},
    ), patch(
        "tools.faith.routes._practice_dispatch",
        return_value={"success": True, "response": "A short prayer."},
    ) as practice_dispatch:
        resp = faith_client.post(
            "/tools/faith/api/faith/prayer",
            json={"prayer_type": "thanksgiving", "intention": "family"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    practice_dispatch.assert_called_once()


@pytest.mark.parametrize("payload", [{}, {"passage": ""}, {"passage": "x" * 501}])
def test_lectio_divina_rejects_invalid_payload_before_dispatch(faith_client, payload):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post("/tools/faith/api/faith/lectio", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    practice_dispatch.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "x" * 2001},
        {"message": "Please contact me.", "journal_ids": "1"},
        {"message": "Please contact me.", "journal_ids": ["abc"]},
        {"message": "Please contact me.", "journal_ids": list(range(21))},
    ],
)
def test_connect_chaplain_rejects_invalid_payload_before_email(faith_client, payload):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._send_chaplain_email") as send_chaplain_email, patch(
        "tools.faith.routes.get_db_cursor"
    ) as get_db_cursor:
        resp = faith_client.post("/tools/faith/api/faith/connect-chaplain", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    send_chaplain_email.assert_not_called()
    get_db_cursor.assert_not_called()


def test_devotional_requires_authentication(faith_client):
    from unittest.mock import patch

    _logout(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.get("/tools/faith/api/faith/devotional")

    assert resp.status_code in (302, 401)
    practice_dispatch.assert_not_called()


def test_devotional_reports_dispatch_failure(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch(
        "tools.faith.routes._get_user_faith_profile",
        return_value={"tradition_preference": "christian", "prayer_style": "guided"},
    ), patch(
        "tools.faith.routes._practice_dispatch",
        return_value={"success": False, "response": "F.A.I.T.H. is unavailable."},
    ):
        resp = faith_client.get("/tools/faith/api/faith/devotional")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert data["response"] == "F.A.I.T.H. is unavailable."


def test_guided_prayer_rejects_malformed_json_before_dispatch(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post(
            "/tools/faith/api/faith/prayer",
            data="{",
            content_type="application/json",
        )

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "prayer_type required"}
    practice_dispatch.assert_not_called()


def test_guided_prayer_rejects_missing_prayer_type_before_dispatch(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post("/tools/faith/api/faith/prayer", json={"intention": "family"})

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "prayer_type required"}
    practice_dispatch.assert_not_called()


def test_lectio_divina_rejects_malformed_json_before_dispatch(faith_client):
    from unittest.mock import patch

    _login(faith_client)
    with patch("tools.faith.routes._practice_dispatch") as practice_dispatch:
        resp = faith_client.post(
            "/tools/faith/api/faith/lectio",
            data="{",
            content_type="application/json",
        )

    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": "passage required"}
    practice_dispatch.assert_not_called()


def test_checkin_history_returns_500_on_database_failure(faith_client):
    from unittest.mock import patch

    from psycopg2 import Error as PsycopgError

    _login(faith_client)
    with patch("tools.faith.routes._ensure_tables"), patch(
        "tools.faith.routes.get_db_cursor",
        side_effect=PsycopgError("database unavailable"),
    ):
        resp = faith_client.get("/tools/faith/api/faith/checkin/history")

    assert resp.status_code == 500
    assert resp.get_json() == {"success": False, "error": "Failed to load"}


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
