"""#5334 cockpit Skills rail — the platform invokable-skills registry in the right rail.

The rail lists the SAME generated registry archie-tui lists (#5333) and dispatches
through DHQ as delegation_source='cockpit'.

The invariant with teeth is the back-compat one: adding a source parameter must NOT
change the EXISTING chat delegation path. That path sends no source, so the hub keeps
defaulting it to 'web_chat'; passing one unconditionally would retroactively relabel
every cockpit chat delegation in task_execution_log and Token Economy.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _client(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    sys.modules.pop("app_comms", None)
    import app_comms

    app_comms.app.config["TESTING"] = True
    app_comms.app.config["SESSION_COOKIE_SECURE"] = False
    app_comms.app.config["SESSION_COOKIE_DOMAIN"] = None
    return app_comms


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


# ---------------------------------------------------------------- back-compat


def test_submit_WITHOUT_source_omits_the_key_entirely(monkeypatch):
    """The existing chat path must send a byte-identical body."""
    ac = _client(monkeypatch)
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(json or {})
        return _Resp({"task_id": 1})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    ac._call_platform_delegation_submit("health_check", "why")
    assert "delegation_source" not in seen, (
        "a source leaked into the existing chat path — that relabels all cockpit chat traffic"
    )
    assert seen["capability"] == "health_check" and seen["reason"] == "why"


def test_submit_WITH_source_includes_it(monkeypatch):
    ac = _client(monkeypatch)
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(json or {})
        return _Resp({"task_id": 2})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    ac._call_platform_delegation_submit("health_check", "why", None, delegation_source="cockpit")
    assert seen["delegation_source"] == "cockpit"


# ---------------------------------------------------------------- registry


def test_registry_helper_hits_the_internal_endpoint_with_the_bearer(monkeypatch):
    ac = _client(monkeypatch)
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = (headers or {}).get("Authorization")
        return _Resp({"skills": [{"capability": "health_check", "kind": "known_tool"}]})

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ac._call_platform_invokable_skills()
    assert seen["url"].endswith("/api/internal/delegation/invokable-skills")
    assert seen["auth"] == "Bearer k"
    assert out["skills"][0]["capability"] == "health_check"


# ---------------------------------------------------------------- routes


def test_skills_routes_require_a_session(monkeypatch):
    ac = _client(monkeypatch)
    with ac.app.test_client() as c:
        assert c.get("/api/skills").status_code == 401
        assert c.post("/api/skills/invoke", json={"capability": "health_check"}).status_code == 401


def test_skills_route_returns_the_registry(monkeypatch):
    ac = _client(monkeypatch)
    monkeypatch.setattr(
        ac, "_call_platform_invokable_skills",
        lambda: {"skills": [{"capability": "run_qa_suite", "kind": "known_tool"}], "llm_count": 0},
    )
    with ac.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
        r = c.get("/api/skills")
        assert r.status_code == 200
        assert json.loads(r.data)["skills"][0]["capability"] == "run_qa_suite"


def test_invoke_route_attributes_to_cockpit(monkeypatch):
    """THE point of the slice."""
    ac = _client(monkeypatch)
    seen = {}

    def fake_submit(cap, reason, args=None, delegation_source=None):
        seen.update({"cap": cap, "reason": reason, "src": delegation_source})
        return {"task_id": 7, "status": "queued"}

    monkeypatch.setattr(ac, "_call_platform_delegation_submit", fake_submit)
    with ac.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
        r = c.post("/api/skills/invoke", json={"capability": "run_qa_suite"})
        assert r.status_code == 200
        assert json.loads(r.data)["task_id"] == 7
    assert seen["src"] == "cockpit"
    assert seen["cap"] == "run_qa_suite"
    assert "run_qa_suite" in seen["reason"]  # a default reason is supplied


def test_invoke_requires_a_capability(monkeypatch):
    ac = _client(monkeypatch)
    with ac.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
        assert c.post("/api/skills/invoke", json={"reason": "no cap"}).status_code == 400


def test_invoke_does_NOT_validate_the_capability_locally(monkeypatch):
    """The hub owns the registry; a local allowlist would go stale on every addition."""
    ac = _client(monkeypatch)
    seen = {}

    def fake_submit(cap, reason, args=None, delegation_source=None):
        seen["cap"] = cap
        return {"task_id": 8, "status": "queued"}

    monkeypatch.setattr(ac, "_call_platform_delegation_submit", fake_submit)
    with ac.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
        r = c.post("/api/skills/invoke", json={"capability": "a_capability_added_next_week"})
        assert r.status_code == 200
    assert seen["cap"] == "a_capability_added_next_week"


def test_invoke_fails_soft_when_the_platform_is_down(monkeypatch):
    ac = _client(monkeypatch)

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(ac, "_call_platform_delegation_submit", boom)
    with ac.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
        r = c.post("/api/skills/invoke", json={"capability": "health_check"})
        assert r.status_code == 503
        assert "error" in json.loads(r.data)


# ---------------------------------------------------------------- XSS


def _strip_js_comments(src):
    """Remove /* */ and // comments.

    Without this the assertion below matches the rail's OWN comment ("No innerHTML
    anywhere here") and passes on prose while the code could regress freely — the
    same trap as asserting on a docstring (KB #293020).
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    return src


def test_rail_never_uses_innerHTML():
    """Registry text is attacker-influenceable in principle; textContent only."""
    js = open(os.path.join(os.path.dirname(__file__), "..", "static", "js", "archie-chat.js")).read()
    # Anchor on CODE, not on the comment banner: slicing from the banner text
    # starts the slice INSIDE the opening /*, so the stripper (which needs both
    # delimiters) leaves the prose behind and the assertion matches the comment
    # "No innerHTML anywhere here" instead of the code.
    block = _strip_js_comments(js[js.index("document.getElementById('ac-skills-list')"):])
    assert "innerHTML" not in block, "the Skills rail must never use innerHTML"
    assert "textContent" in block
