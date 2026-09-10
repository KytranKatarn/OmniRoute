"""#6653 Phase 4 — the cockpit Blueprint: session-gated, thin, pass-through."""

from pathlib import Path

from flask import Flask

import cockpit_routes as cr
import services.cockpit_proxy as cp

ROOT = Path(__file__).resolve().parents[1]  # archie-comms/


def _app():
    # Absolute folders: Flask(__name__) would otherwise look for tests/templates.
    app = Flask("cockpit_test", template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.secret_key = "t"
    app.register_blueprint(cr.cockpit_bp)
    return app


def _login(client):
    with client.session_transaction() as s:
        s["user_id"] = 4


def test_page_redirects_to_login_without_a_session():
    c = _app().test_client()
    r = c.get("/cockpit")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login?next=/cockpit")


def test_api_is_401_without_a_session():
    c = _app().test_client()
    assert c.get("/api/cockpit/agents").status_code == 401
    assert c.post("/api/cockpit/build/run", json={"prompt": "x"}).status_code == 401


def test_agents_list_passes_query_and_status_through(monkeypatch):
    monkeypatch.setattr(cp, "list_agents", lambda params: (200, {"success": True, "agents": [], "total": 0, "q": params.get("q")}))
    c = _app().test_client()
    _login(c)
    r = c.get("/api/cockpit/agents?q=forge")
    assert r.status_code == 200 and r.get_json()["q"] == "forge"


def test_agent_action_routes_map_to_proxy_actions(monkeypatch):
    seen = []
    monkeypatch.setattr(cp, "agent_action", lambda agent_id, action, body: seen.append((agent_id, action, body)) or (200, {"success": True}))
    c = _app().test_client()
    _login(c)
    for path, action in (("assign", "assign"), ("shift-state", "shift-state"), ("skills/add", "skills/add"), ("skills/remove", "skills/remove"), ("budget", "budget")):
        assert c.post(f"/api/cockpit/agents/12/{path}", json={"x": 1}).status_code == 200
    assert [a for _, a, _ in seen] == ["assign", "shift-state", "skills/add", "skills/remove", "budget"]
    assert seen[0][0] == 12 and seen[0][2] == {"x": 1}


def test_hub_errors_are_returned_verbatim(monkeypatch):
    monkeypatch.setattr(cp, "build_run", lambda body: (409, {"success": False, "status": "approval_unavailable", "error": "one pending"}))
    c = _app().test_client()
    _login(c)
    r = c.post("/api/cockpit/build/run", json={"prompt": "x"})
    assert r.status_code == 409 and r.get_json()["error"] == "one pending"


def test_build_status_and_runs(monkeypatch):
    monkeypatch.setattr(cp, "build_status", lambda job_id: (200, {"success": True, "job_id": job_id}))
    monkeypatch.setattr(cp, "build_runs", lambda limit=20: (200, {"success": True, "runs": [], "limit": limit}))
    c = _app().test_client()
    _login(c)
    assert c.get("/api/cockpit/build/1198308").get_json()["job_id"] == 1198308
    assert c.get("/api/cockpit/build/runs?limit=5").get_json()["limit"] == 5


def test_page_renders_for_a_session():
    c = _app().test_client()
    _login(c)
    r = c.get("/cockpit")
    assert r.status_code == 200 and b'id="pane-crew"' in r.data and b'id="pane-builder"' in r.data
