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


# ── #6666: a malformed approval id is a 400, never a 500 ─────────────────────


def test_parse_approval_id_rejects_a_bare_numeric_id_with_an_actionable_message():
    """`'15231'.partition(':')` yields ('15231','',''), so the old code put an empty
    string into int() and raised `invalid literal for int() with base 10: ''` — which
    surfaced as a 500 {"error_type":"ValueError"} from archie_comms on 2026-09-09.

    The message must name the expected form; the bare int() error told the caller
    nothing about what to send instead.
    """
    import pytest

    ar = importlib.import_module("tools.department_hq.approvals_routes")
    with pytest.raises(ValueError) as exc:
        ar.parse_approval_id("15231")
    msg = str(exc.value)
    assert "malformed approval id" in msg
    assert "<source>:<int>" in msg, "the error must state the expected form"
    assert "autonomy" in msg, "the error must name at least one valid source"


def test_parse_approval_id_rejects_the_other_malformed_shapes():
    import pytest

    ar = importlib.import_module("tools.department_hq.approvals_routes")
    for bad in ("", ":", "autonomy:", ":123", "autonomy:abc", "autonomy:12x"):
        with pytest.raises(ValueError):
            ar.parse_approval_id(bad)


def test_a_bare_id_is_NOT_silently_treated_as_autonomy():
    """Deliberate refusal, not an oversight. autonomy_approval_queue.id,
    contractor_approval_requests.id and bridge_jobs.id are independent sequences, so
    a bare '5' is genuinely ambiguous — guessing on an APPROVE route could approve a
    different pending item than the caller meant. Callers already have the prefixed
    form: list_pending_approvals() returns source-prefixed ids.
    """
    import pytest

    ar = importlib.import_module("tools.department_hq.approvals_routes")
    with pytest.raises(ValueError):
        ar.parse_approval_id("5")


def test_the_valid_form_still_parses():
    """The fix must not narrow what already worked."""
    ar = importlib.import_module("tools.department_hq.approvals_routes")
    assert ar.parse_approval_id("autonomy:123") == ("autonomy", 123)
    assert ar.parse_approval_id("contractor:7") == ("contractor", 7)
    assert ar.parse_approval_id("bridge:99") == ("bridge", 99)
