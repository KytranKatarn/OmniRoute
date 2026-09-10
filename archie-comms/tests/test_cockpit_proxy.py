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


def test_task_reads_forward_allowed_params_only(monkeypatch):
    seen = []

    def fake_request(method, url, json=None, headers=None, timeout=None, params=None):
        seen.append((method, url, params))
        return _Resp(200, {"success": True, "tasks": [], "total": 0})

    monkeypatch.setattr(cp.requests, "request", fake_request)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    cp.list_projects({"status": "active", "limit": "5", "evil": "1"})
    cp.list_tasks({"q": "x", "project_id": "343", "status": "pending", "min_priority": "8", "limit": "50", "offset": "50", "evil": "1"})
    cp.get_task(12)
    assert seen[0][:2] == ("GET", cp._base() + "/api/internal/projects") and seen[0][2] == {"status": "active", "limit": "5"}
    assert seen[1][1].endswith("/api/internal/tasks") and seen[1][2] == {"q": "x", "project_id": "343", "status": "pending", "min_priority": "8", "limit": "50", "offset": "50"}
    assert seen[2][1].endswith("/api/internal/tasks/12")


def test_task_writes_post_bodies_and_refuse_unknown_actions(monkeypatch):
    seen = []
    monkeypatch.setattr(cp.requests, "request", lambda m, u, json=None, headers=None, timeout=None, params=None: seen.append((m, u, json, timeout)) or _Resp(200, {"success": True}))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    cp.create_task({"project_id": 343, "title": "T"})
    cp.task_action(12, "delegate", {"capability": "research"})
    status, body = cp.task_action(12, "delete", {})
    assert status == 400 and "unknown action" in body["error"]
    assert seen[0][:3] == ("POST", cp._base() + "/api/internal/tasks", {"project_id": 343, "title": "T"}) and seen[0][3] == 30
    assert seen[1][1].endswith("/api/internal/tasks/12/delegate") and seen[1][2] == {"capability": "research"}
    assert len(seen) == 2


def test_build_apply_and_target_path_passthrough(monkeypatch):
    seen = []
    monkeypatch.setattr(cp.requests, "request", lambda m, u, json=None, headers=None, timeout=None, params=None: seen.append((m, u, json)) or _Resp(202, {"success": True, "approval_id": 9}))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    cp.build_run({"prompt": "p", "provider": "omniroute", "model": "oc/big-pickle", "target_path": "docs/a.md"})
    status, body = cp.build_apply(1202345)
    assert seen[0][2]["target_path"] == "docs/a.md"
    assert seen[1][:2] == ("POST", cp._base() + "/api/internal/cloud-code/run/1202345/apply") and status == 202 and body["approval_id"] == 9
