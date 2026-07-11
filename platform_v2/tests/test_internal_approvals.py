"""Cockpit-facing internal approvals surface (COO Cockpit Slice 1).

The archie_comms cockpit approves/denies Tier-2 findings (the 77 red Code-Health
cards) through @_require_internal_key platform endpoints that wrap the EXISTING
_approve_autonomy/_deny_autonomy/approvals_pending logic. These pin:
  - the two shared callables extracted for reuse (parse_approval_id +
    list_pending_approvals) — plain functions, no Flask/session, and
  - the three internal endpoints (pending / approve / deny), Bearer-gated,
    owner-id defaulted, fail-closed.
"""

import importlib


def test_parse_approval_id_splits_source_and_int():
    ar = importlib.import_module("tools.department_hq.approvals_routes")
    assert ar.parse_approval_id("autonomy:123") == ("autonomy", 123)
    assert ar.parse_approval_id("contractor:7") == ("contractor", 7)


def test_list_pending_approvals_is_callable_without_flask():
    ar = importlib.import_module("tools.department_hq.approvals_routes")
    # must be a plain function (no request/current_user access) returning a list
    result = ar.list_pending_approvals()
    assert isinstance(result, list)


# ── internal approve/deny endpoints (Task 2) ──────────────────────────────────
# The `client` fixture (conftest) builds the Flask app from ARCHIE_APP_PY, so the
# bundle's app.py + its new endpoints are exercised. The endpoints import the
# executors at call time, so monkeypatching the module attribute takes effect.


def test_internal_approve_requires_key(client):
    r = client.post("/api/internal/approvals/autonomy:123/approve", json={})
    assert r.status_code == 401


def test_internal_approve_routes_to_executor(client, monkeypatch):
    import tools.department_hq.approvals_routes as ar

    seen = {}
    monkeypatch.setattr(
        ar,
        "_approve_autonomy",
        lambda sid, uid: seen.update(sid=sid, uid=uid) or (True, "improvement_approve_red"),
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/approvals/autonomy:123/approve",
        json={"user_id": 2},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["action_type"] == "improvement_approve_red"
    assert seen == {"sid": 123, "uid": 2}


def test_internal_approve_defaults_owner_id(client, monkeypatch):
    import tools.department_hq.approvals_routes as ar

    seen = {}
    monkeypatch.setattr(
        ar,
        "_approve_autonomy",
        lambda sid, uid: seen.update(sid=sid, uid=uid) or (True, "improvement_approve"),
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    # no user_id in the body -> defaults to Kytran (owner user_id=2)
    r = client.post(
        "/api/internal/approvals/autonomy:9/approve",
        json={},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    assert seen == {"sid": 9, "uid": 2}


def test_internal_deny_routes_to_executor(client, monkeypatch):
    import tools.department_hq.approvals_routes as ar

    seen = {}
    monkeypatch.setattr(
        ar,
        "_deny_autonomy",
        lambda sid, uid, reason: seen.update(sid=sid, uid=uid, reason=reason) or True,
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/approvals/autonomy:5/deny",
        json={"user_id": 2, "reason": "not now"},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert seen == {"sid": 5, "uid": 2, "reason": "not now"}


def test_internal_approve_non_autonomy_source_501(client, monkeypatch):
    # Slice 1 targets the red autonomy cards; contractor/bridge are 501 for now.
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/approvals/contractor:3/approve",
        json={},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 501
    assert r.get_json()["ok"] is False
