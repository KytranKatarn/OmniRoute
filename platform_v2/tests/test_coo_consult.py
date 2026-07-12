"""COO consult — platform side (Slice 1 of the COO command surface).

The cockpit consults an agent/department: resolve the target to a dispatchable agent,
dispatch via DHQ, return the answer. She relays it in her own voice cockpit-side.
"""


def test_list_consultable_agents_returns_directors(monkeypatch):
    import services.coo_consult_service as svc

    monkeypatch.setattr(
        svc,
        "_list_agents",
        lambda **k: [
            {
                "name": "V.I.G.I.L.",
                "department": "Security & Compliance",
                "is_department_ai": True,
                "title": "Director",
            },
            {
                "name": "R.E.S.O.L.V.E.",
                "department": "Customer Success & Support",
                "is_department_ai": True,
                "title": "Director",
            },
        ],
    )
    out = svc.list_consultable_agents()
    names = [a["name"] for a in out]
    assert "V.I.G.I.L." in names and "R.E.S.O.L.V.E." in names
    assert all({"name", "department", "is_department_ai"} <= set(a) for a in out)


def test_resolve_agent_name_case_insensitive(monkeypatch):
    import services.coo_consult_service as svc

    monkeypatch.setattr(
        svc, "_list_agents", lambda **k: [{"name": "V.I.G.I.L.", "department": "Security & Compliance"}]
    )
    monkeypatch.setattr(svc, "_capability_department_map", lambda: {"security": "Security & Compliance"})
    r = svc.resolve_consult_target("v.i.g.i.l.")
    assert r == {"agent_name": "V.I.G.I.L.", "department": "Security & Compliance", "capability": "security"}


def test_resolve_department_to_director(monkeypatch):
    import services.coo_consult_service as svc

    calls = {}

    def fake_list(**k):
        if k.get("is_department_ai"):
            calls["dept"] = k.get("department")
            return [{"name": "V.I.G.I.L.", "department": "Security & Compliance"}]
        return []  # no agent-name match

    monkeypatch.setattr(svc, "_list_agents", fake_list)
    monkeypatch.setattr(svc, "_capability_department_map", lambda: {"security": "Security & Compliance"})
    r = svc.resolve_consult_target("security")
    assert r["agent_name"] == "V.I.G.I.L." and r["capability"] == "security"
    assert calls["dept"] == "Security & Compliance"


def test_resolve_unknown_returns_none(monkeypatch):
    import services.coo_consult_service as svc

    monkeypatch.setattr(svc, "_list_agents", lambda **k: [])
    monkeypatch.setattr(svc, "_capability_department_map", lambda: {"security": "Security & Compliance"})
    assert svc.resolve_consult_target("nobody") is None


def test_agents_endpoint_requires_key(client):
    r = client.get("/api/internal/coo/agents")
    assert r.status_code == 401


def test_agents_endpoint_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coo_consult_service as svc

    monkeypatch.setattr(
        svc,
        "list_consultable_agents",
        lambda: [
            {"name": "V.I.G.I.L.", "department": "Security & Compliance", "is_department_ai": True, "title": "Director"}
        ],
    )
    r = client.get("/api/internal/coo/agents", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["agents"][0]["name"] == "V.I.G.I.L."
    assert "Security & Compliance" in body["departments"]


def test_consult_requires_key(client):
    r = client.post("/api/internal/coo/consult", json={"target": "V.I.G.I.L.", "prompt": "hi"})
    assert r.status_code == 401


def test_consult_unknown_target(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coo_consult_service as svc

    monkeypatch.setattr(svc, "resolve_consult_target", lambda t: None)
    r = client.post(
        "/api/internal/coo/consult",
        json={"target": "nobody", "prompt": "hi"},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200 and r.get_json()["success"] is False
    assert r.get_json()["error"] == "unknown_target"


def test_consult_dispatches_to_resolved_agent(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coo_consult_service as svc

    monkeypatch.setattr(
        svc,
        "resolve_consult_target",
        lambda t: {"agent_name": "V.I.G.I.L.", "department": "Security & Compliance", "capability": "security"},
    )
    seen = {}
    import tools.department_hq.services.department_dispatcher as dd

    class _R:
        success = True
        response = "Firewall is clean."
        agent_name = "V.I.G.I.L."
        model_used = "qwen2.5:7b"

    monkeypatch.setattr(dd, "dispatch", lambda **k: seen.update(k) or _R())
    r = client.post(
        "/api/internal/coo/consult",
        json={"target": "V.I.G.I.L.", "prompt": "firewall?"},
        headers={"Authorization": "Bearer k"},
    )
    b = r.get_json()
    assert b["success"] and b["agent_name"] == "V.I.G.I.L." and b["resolved_target"] == "V.I.G.I.L."
    assert seen["prefer_agent"] == "V.I.G.I.L." and seen["capability"] == "security" and seen["local_only"] is True
