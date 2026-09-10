"""#6679 Phase 4b — the cockpit Work pane routes: scope-gated, thin, hub errors verbatim.
Runs in-container: docker exec -i archie_platform python3 -m pytest /app/tests/test_cockpit_task_routes.py -q
"""

import pytest

from services import internal_auth as ia
from services import task_service as ts

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.delenv(ia.LEGACY_ENV, raising=False)
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


def _h(caller="archie_comms"):
    return {"Authorization": f"Bearer {CALLER_KEYS[caller]}"}


def test_no_key_is_401_and_engine_key_is_403(client, keys):
    assert client.get("/api/internal/tasks").status_code == 401
    assert client.get("/api/internal/tasks", headers=_h("archie_engine")).status_code == 403
    assert client.post("/api/internal/tasks/1/note", headers=_h("archie_engine"), json={"text": "x"}).status_code == 403


def test_projects_list_passes_filters_and_echoes_paging(client, keys, monkeypatch):
    seen = {}

    def fake(status=None, limit=50, offset=0):
        seen.update(status=status, limit=limit, offset=offset)
        return [{"id": 343, "name": "Master", "open_tasks": 4, "total_tasks": 9}], 1

    monkeypatch.setattr(ts, "list_projects", fake)
    r = client.get("/api/internal/projects?status=active&limit=500&offset=-2", headers=_h())
    assert r.status_code == 200
    body = r.get_json()
    assert body["projects"][0]["name"] == "Master" and body["total"] == 1
    assert body["limit"] == 200 and body["offset"] == 0
    assert seen["status"] == "active"


def test_tasks_list_returns_facets(client, keys, monkeypatch):
    monkeypatch.setattr(
        ts,
        "list_tasks",
        lambda **kw: (
            [{"id": 1, "title": "t"}],
            1,
            {"status": {"pending": 1}, "projects": {}, "capabilities": ["code"]},
        ),
    )
    body = client.get("/api/internal/tasks?q=t&project_id=343&min_priority=8", headers=_h()).get_json()
    assert body["success"] and body["facets"]["capabilities"] == ["code"] and body["tasks"][0]["id"] == 1


def test_bad_filter_is_400_verbatim(client, keys, monkeypatch):
    def boom(**kw):
        raise ValueError("unknown status 'bogus'; allowed: pending")

    monkeypatch.setattr(ts, "list_tasks", boom)
    r = client.get("/api/internal/tasks?status=bogus", headers=_h())
    assert r.status_code == 400 and r.get_json()["error"].startswith("unknown status 'bogus'")


def test_task_detail_404(client, keys, monkeypatch):
    monkeypatch.setattr(ts, "get_task", lambda tid: None)
    assert client.get("/api/internal/tasks/99", headers=_h()).status_code == 404


def test_create_task_is_201(client, keys, monkeypatch):
    seen = {}

    def fake(project_id, title, description="", priority=5, task_type="implementation", requested_by="cockpit"):
        seen.update(
            project_id=project_id, title=title, priority=priority, task_type=task_type, requested_by=requested_by
        )
        return {"id": 5, "title": title, "status": "pending"}

    monkeypatch.setattr(ts, "create_task", fake)
    r = client.post(
        "/api/internal/tasks",
        headers=_h(),
        json={"project_id": 343, "title": "T", "priority": 7, "task_type": "bugfix"},
    )
    assert r.status_code == 201 and r.get_json()["task"]["id"] == 5
    assert seen == {"project_id": 343, "title": "T", "priority": 7, "task_type": "bugfix", "requested_by": "cockpit"}


def test_task_actions_map_to_service(client, keys, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ts,
        "set_status",
        lambda tid, s, requested_by="cockpit": calls.append(("status", tid, s)) or {"id": tid, "status": s},
    )
    monkeypatch.setattr(
        ts,
        "set_priority",
        lambda tid, p, requested_by="cockpit": calls.append(("priority", tid, p)) or {"id": tid, "priority": p},
    )
    monkeypatch.setattr(
        ts,
        "add_note",
        lambda tid, t, author="cockpit": calls.append(("note", tid, t)) or {"ts": "now", "author": author, "text": t},
    )
    monkeypatch.setattr(ts, "get_task", lambda tid: {"id": tid})
    monkeypatch.setattr(
        ts,
        "delegate",
        lambda tid, c, requested_by="cockpit": calls.append(("delegate", tid, c))
        or {"id": tid, "delegation_source": "cockpit"},
    )
    assert client.post("/api/internal/tasks/7/status", headers=_h(), json={"status": "blocked"}).status_code == 200
    assert client.post("/api/internal/tasks/7/priority", headers=_h(), json={"priority": 9}).status_code == 200
    r = client.post("/api/internal/tasks/7/note", headers=_h(), json={"text": "hi"})
    assert r.status_code == 200 and r.get_json()["note"]["text"] == "hi" and r.get_json()["task"]["id"] == 7
    r = client.post("/api/internal/tasks/7/delegate", headers=_h(), json={"capability": "research"})
    assert (
        r.status_code == 202
        and r.get_json()["worker"] == "delegate_task_worker"
        and r.get_json()["claims_within_s"] == 30
    )
    assert calls == [("status", 7, "blocked"), ("priority", 7, 9), ("note", 7, "hi"), ("delegate", 7, "research")]


def test_lookup_error_is_404_and_value_error_is_400(client, keys, monkeypatch):
    def missing(*a, **k):
        raise LookupError("task not found")

    def bad(*a, **k):
        raise ValueError("only pending or blocked tasks can be delegated (this one is completed)")

    monkeypatch.setattr(ts, "set_status", missing)
    monkeypatch.setattr(ts, "delegate", bad)
    assert client.post("/api/internal/tasks/1/status", headers=_h(), json={"status": "pending"}).status_code == 404
    r = client.post("/api/internal/tasks/1/delegate", headers=_h(), json={"capability": "research"})
    assert r.status_code == 400 and "only pending or blocked" in r.get_json()["error"]
