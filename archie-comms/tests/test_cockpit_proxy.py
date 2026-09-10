"""#6653 Phase 4 — thin cockpit->hub proxy. Passes the hub's status + JSON through
verbatim (the UI shows the hub's own error text); fail-CLOSED on transport/config."""

import services.cockpit_proxy as cp


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


def test_list_agents_forwards_query_and_bearer(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.update(method=method, url=url, headers=headers, timeout=timeout, params=params)
        return _Resp(200, {"success": True, "agents": [], "total": 0})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.list_agents({"q": "forge", "limit": "10"})
    assert status == 200 and body["total"] == 0
    assert seen["method"] == "GET" and seen["url"].endswith("/api/internal/agents")
    assert seen["params"] == {"q": "forge", "limit": "10"} and seen["headers"]["Authorization"] == "Bearer k"
    assert seen["timeout"] == 15


def test_writes_use_30s_and_pass_hub_errors_verbatim(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.update(method=method, url=url, json=json, timeout=timeout)
        return _Resp(400, {"success": False, "error": "skill_name required"})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.agent_action(12, "skills/add", {"skill_name": ""})
    assert status == 400 and body["error"] == "skill_name required"
    assert seen["method"] == "POST" and seen["url"].endswith("/api/internal/agents/12/skills/add") and seen["timeout"] == 30


def test_unknown_action_is_refused_locally(monkeypatch):
    called = []
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: called.append(1))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.agent_action(12, "delete", {})
    assert status == 400 and "unknown action" in body["error"] and not called


def test_missing_key_is_503_without_a_request(monkeypatch):
    called = []
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: called.append(1))
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    status, body = cp.build_providers()
    assert status == 503 and "not configured" in body["error"] and not called


def test_transport_error_is_503_hub_unreachable(monkeypatch):
    def boom(*a, **k):
        raise cp.requests.ConnectionError("refused")

    monkeypatch.setattr(cp.requests, "request", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.build_status(1198308)
    assert status == 503 and body["error"].startswith("hub unreachable")


def test_non_json_hub_reply_becomes_an_error_dict(monkeypatch):
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: _Resp(502, ValueError("not json")))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.build_runs(5)
    assert status == 502 and body == {"success": False, "error": "HTTP 502"}


def test_build_run_posts_prompt_and_model(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.update(method=method, url=url, json=json)
        return _Resp(202, {"success": True, "status": "pending_approval", "job_id": 1, "approval_id": 2})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    status, body = cp.build_run({"prompt": "hi", "model": "oc/big-pickle", "provider": "omniroute"})
    assert status == 202 and body["job_id"] == 1 and seen["url"].endswith("/api/internal/cloud-code/run")
    assert seen["json"] == {"prompt": "hi", "model": "oc/big-pickle", "provider": "omniroute"}
