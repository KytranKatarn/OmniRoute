"""#7261 — the Dev HQ project-level write routes: scoped to coder_lanes, pass-throughs.

The archie-project skill names create_project / log_decision /
update_project_understanding, but before #7261 the gateway exposed none of them —
write tools it cannot reach are withheld (read-only DB role) and no /api/internal
route existed for the project-level writes at all. Agents hit "Unknown tool" and
improvised: on 2026-10-15 a project row had to be hand-INSERTed from a lane,
mirroring mcp_server/tools/project_tools.py:create_project_handler by hand.

These routes are thin pass-throughs to the MCP server's own handlers, fenced by
the devhq:write scope held ONLY by coder_lanes. The tests monkeypatch those
handlers: what is under test here is the SCOPE GATE and the plumbing, not a
second copy of the handlers' DB behavior.

complete_task needs no route — the gateway composes the two audited task routes
(note first, then status), so it is covered in test_coder_lane_task_scopes.

Runs in-container:
    docker exec -i archie_platform python3 -m pytest tests/test_internal_devhq_routes.py -q
or against a worktree, via scripts/run_tests.sh (ephemeral container, archie_test DB).
"""

import pytest

from services import internal_auth as ia

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}

ROUTES = [
    ("POST", "/api/internal/projects"),
    ("POST", "/api/internal/decisions"),
    ("POST", "/api/internal/projects/1/understanding"),
]


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.delenv(ia.LEGACY_ENV, raising=False)
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


def _h(caller):
    return {"Authorization": f"Bearer {CALLER_KEYS[caller]}"}


def _post(client, path, caller=None, json=None):
    headers = _h(caller) if caller else {}
    return client.post(path, headers=headers, json=json if json is not None else {})


def test_no_key_is_401_and_out_of_scope_is_403(client, keys):
    for method, path in ROUTES:
        assert _post(client, path).status_code == 401, (method, path)
        # archie_engine holds tasks:write but must NOT reach the devhq:write family
        r = _post(client, path, "archie_engine")
        assert r.status_code == 403, (method, path, r.status_code)
        body = r.get_json()
        assert body["error"] == "scope_denied"
        assert body["caller"] == "archie_engine" and body["required"] == "devhq:write"


def test_coder_lanes_reach_the_handlers_with_the_original_arguments(client, keys, monkeypatch):
    import mcp_server.tools.project_tools as pt

    seen = {}

    async def fake_create(args):
        seen["create"] = args
        return {"success": True, "project_id": 1, "slug": "probe", "message": "ok"}

    async def fake_decision(args):
        seen["decision"] = args
        return {"success": True, "decision_id": 9, "adr_number": "ADR-007", "message": "ok"}

    async def fake_understanding(args):
        seen["understanding"] = args
        return {"success": True, "understanding": 40, "emotion": "curious", "message": "ok"}

    monkeypatch.setattr(pt, "create_project_handler", fake_create)
    monkeypatch.setattr(pt, "log_decision_handler", fake_decision)
    monkeypatch.setattr(pt, "update_project_understanding_handler", fake_understanding)

    r = _post(client, "/api/internal/projects", "coder_lanes", {"name": "Probe"})
    assert r.status_code == 201 and r.get_json()["project_id"] == 1
    assert seen["create"]["name"] == "Probe"

    r = _post(client, "/api/internal/decisions", "coder_lanes", {"title": "T", "decision": "D"})
    assert r.status_code == 201 and r.get_json()["adr_number"] == "ADR-007"
    assert seen["decision"]["title"] == "T" and seen["decision"]["decision"] == "D"

    # the PATH project_id wins over whatever the body claims
    r = _post(client, "/api/internal/projects/7/understanding", "coder_lanes", {"project_id": 999, "notes": "n"})
    assert r.status_code == 200
    assert seen["understanding"]["project_id"] == 7 and seen["understanding"]["notes"] == "n"


def test_handler_refusal_passes_through_as_400(client, keys, monkeypatch):
    """A handler's own validation error must read verbatim — comms renders it as-is."""
    import mcp_server.tools.project_tools as pt

    async def refuse(args):
        return {"success": False, "error": "Project name is required"}

    monkeypatch.setattr(pt, "create_project_handler", refuse)
    r = _post(client, "/api/internal/projects", "coder_lanes", {})
    assert r.status_code == 400
    assert r.get_json()["error"] == "Project name is required"


def test_scope_table_still_holds_for_the_new_family():
    """The invariant the design leans on: devhq:write exists, is held by exactly one
    caller, and nobody holds every scope."""
    assert "devhq:write" in ia.SCOPES
    holders = [c for c, s in ia.CALLER_SCOPES.items() if "devhq:write" in s]
    assert holders == ["coder_lanes"]
    assert ia.CALLER_SCOPES["coder_lanes"] < ia.SCOPES
