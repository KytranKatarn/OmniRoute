"""Tools & Actions — platform side (Slice 4 of the COO command surface).

A curated SAFE catalog of known-tool diagnostics she runs from the cockpit; run_action executes
them synchronously via the delegation service. Only catalog keys run — nothing state-changing.
"""


def test_list_actions_is_curated_safe():
    import services.coo_actions_service as svc

    out = svc.list_actions()
    keys = {a["key"] for a in out}
    assert "health" in keys and "qa" in keys
    caps = {svc._CATALOG[a["key"]]["capability"] for a in out}
    assert not (caps & {"deploy_static", "deploy_vps", "restore_production", "run_misroute_to_proposal_adapter"})


def test_run_action_rejects_unknown_key():
    import services.coo_actions_service as svc

    assert svc.run_action("nope")["ok"] is False
    assert svc.run_action("deploy_vps")["ok"] is False


def test_run_action_executes_known_tool(client, monkeypatch):
    # `client` boots the app so delegation_service imports with the ai_bridge path (KB #272154).
    import services.coo_actions_service as svc
    import services.delegation_service as dsvc

    seen = {}
    monkeypatch.setattr(
        dsvc,
        "_execute_known_tool",
        lambda cap, payload, reason: seen.update(cap=cap)
        or {"success": True, "summary": "All green", "result": {"ok": 1}},
    )
    out = svc.run_action("health")
    assert out["ok"] and out["summary"] == "All green" and seen["cap"] == "check_platform_health"


def test_actions_catalog_endpoint(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.get("/api/internal/actions/catalog", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and any(a["key"] == "health" for a in r.get_json()["actions"])


def test_actions_run_endpoint_requires_key(client):
    assert client.post("/api/internal/actions/run", json={"key": "health"}).status_code == 401
