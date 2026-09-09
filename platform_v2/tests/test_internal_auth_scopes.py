"""#6657 — the internal API is scoped per caller; nobody holds everything.

Before: 44 /api/internal/* routes behind one flat INTERNAL_API_KEY shared by seven
compose services (plus media_hub and KSO), compared with `!=`, plus three other
implementations — one of which FAILED OPEN when its env var was unset. Whoever held
the key (e.g. by reading it off the engine's unauthenticated websocket) could clear a
Tier-2 human approval, export Playwright session cookies and read owner mail.

Now: services/internal_auth.py — per-caller keys from the environment, a static
caller → scope table, ONE decorator, hmac.compare_digest, DB-free, fail-closed, and
the legacy flat key accepted as full scope (with a WARNING) only while
INTERNAL_KEY_LEGACY_ACCEPT != "0".

Runs in-container (needs /app/app.py):
    docker exec -i archie_platform python3 -m pytest tests/test_internal_auth_scopes.py -q
"""

import logging
import os

import pytest

from services import internal_auth as ia

CALLER_KEYS = {caller: f"key-for-{caller}" for caller in ia.CALLER_ENV}
LEGACY = "legacy-flat-key"

# Representative routes per scope — one in-scope and one out-of-scope probe per caller
# is enough to prove the table binds; the completeness test proves every route is IN
# the table.
PROBES = {
    "dhq:chat": ("POST", "/api/internal/dhq/chat"),
    "coo": ("GET", "/api/internal/coo/agents"),
    "mail": ("GET", "/api/internal/mail/inbox"),
    "approvals:read": ("GET", "/api/internal/approvals/pending"),
    "approvals:decide": ("POST", "/api/internal/approvals/autonomy:0/deny"),
    "approvals:request": ("GET", "/api/internal/approval/0"),
    "delegation": ("GET", "/api/internal/delegation/invokable-skills"),
    "engine": ("POST", "/api/internal/engine/telemetry"),
    "repair:read": ("GET", "/api/internal/repair/count"),
    "repair:write": ("POST", "/api/internal/repair/scan"),
    "sessions": ("GET", "/api/internal/linkedin/challenge-code"),
    "fleet": ("GET", "/api/internal/fleet-gpu-load"),
    "notify": ("POST", "/api/internal/notify"),
}


@pytest.fixture
def keys(monkeypatch):
    for caller, env in ia.CALLER_ENV.items():
        monkeypatch.setenv(env, CALLER_KEYS[caller])
    monkeypatch.setenv(ia.LEGACY_ENV, LEGACY)
    monkeypatch.delenv(ia.LEGACY_ACCEPT_ENV, raising=False)
    return CALLER_KEYS


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _hit(client, method, path, headers):
    fn = getattr(client, method.lower())
    return fn(path, headers=headers, json={} if method == "POST" else None)


# ── the table itself ─────────────────────────────────────────────────────────


def test_every_scope_is_granted_and_nobody_holds_everything():
    granted = set().union(*ia.CALLER_SCOPES.values())
    # Every declared scope is granted to at least one caller (no dead scopes —
    # `access:check` was one, and was removed with the watch grant that held it).
    assert granted == ia.SCOPES
    for caller, scopes in ia.CALLER_SCOPES.items():
        assert scopes < ia.SCOPES, f"{caller} holds every scope"
        assert scopes, f"{caller} holds nothing"


def test_sharp_edges_are_where_the_design_put_them():
    assert "approvals:decide" in ia.CALLER_SCOPES["archie_comms"]  # the owner's approval surface
    assert "approvals:decide" not in ia.CALLER_SCOPES["archie_engine"]
    assert "sessions" not in ia.CALLER_SCOPES["archie_engine"]
    assert "mail" not in ia.CALLER_SCOPES["archie_engine"]
    assert ia.CALLER_SCOPES["browser"] == {"sessions"}
    assert ia.CALLER_SCOPES["scripts"] == {"notify"}


def test_unknown_scope_is_a_programming_error():
    with pytest.raises(ValueError):
        ia.require_internal_scope("not-a-scope")


# ── completeness: a future internal route cannot ship unscoped ───────────────


def test_every_internal_route_is_scoped(app):
    unscoped = []
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/internal/") or rule.rule.endswith("/api/internal/notify"):
            if rule.endpoint.split(".")[-1] not in ia._SCOPED_ENDPOINTS:
                unscoped.append(f"{rule.rule} -> {rule.endpoint}")
    assert not unscoped, "internal routes without require_internal_scope:\n" + "\n".join(unscoped)
    assert len([r for r in app.url_map.iter_rules() if r.rule.startswith("/api/internal/")]) >= 44


# ── the gate, through the real Flask routes ──────────────────────────────────


@pytest.mark.parametrize("caller", sorted(ia.CALLER_SCOPES))
def test_each_caller_passes_in_scope_and_is_403_out_of_scope(client, keys, caller):
    scopes = ia.CALLER_SCOPES[caller]
    probe_in = next((PROBES[s] for s in sorted(scopes) if s in PROBES), None)
    probe_out = next((PROBES[s] for s in sorted(ia.SCOPES - scopes) if s in PROBES), None)
    if probe_in:
        r = _hit(client, *probe_in, _bearer(keys[caller]))
        assert r.status_code not in (401, 403), f"{caller} refused on its own scope {probe_in}: {r.status_code}"
    if probe_out:
        r = _hit(client, *probe_out, _bearer(keys[caller]))
        assert r.status_code == 403, f"{caller} reached {probe_out}: {r.status_code}"
        body = r.get_json()
        assert body["error"] == "scope_denied" and body["caller"] == caller and body["required"]


def test_both_header_forms_are_accepted(client, keys):
    for headers in (_bearer(keys["scripts"]), {"X-Internal-Key": keys["scripts"]}):
        r = client.post("/api/internal/notify", headers=headers, json={"message": "x", "priority": "low"})
        assert r.status_code == 200, headers


def test_no_key_is_401_and_a_wrong_key_is_401(client, keys):
    assert client.get("/api/internal/repair/count").status_code == 401
    assert client.get("/api/internal/repair/count", headers=_bearer("nope")).status_code == 401
    assert (
        client.get("/api/internal/repair/count", headers={"Authorization": keys["archie_comms"]}).status_code == 401
    )  # no scheme


def test_unset_environment_fails_closed_everywhere(client, monkeypatch):
    for env in list(ia.CALLER_ENV.values()) + [ia.LEGACY_ENV]:
        monkeypatch.delenv(env, raising=False)
    for headers in ({}, _bearer(""), _bearer("anything"), {"X-Internal-Key": "anything"}):
        assert client.post("/api/internal/notify", headers=headers, json={"message": "x"}).status_code == 401
        assert (
            client.post("/tools/account-center/api/internal/notify", headers=headers, json={"message": "x"}).status_code
            == 401
        )


def test_account_center_notify_no_longer_fails_open(client, keys, monkeypatch):
    """The old handler accepted EVERY request when ARCHIE_INTERNAL_KEY was unset."""
    monkeypatch.delenv("ARCHIE_INTERNAL_KEY", raising=False)
    assert client.post("/tools/account-center/api/internal/notify", json={"message": "x"}).status_code == 401
    r = client.post(
        "/tools/account-center/api/internal/notify", headers={"X-Internal-Key": keys["kbs"]}, json={"message": "x"}
    )
    assert r.status_code == 200


def test_archie_internal_key_is_accepted_as_a_legacy_alias(client, keys, monkeypatch, caplog):
    """KBS presents ARCHIE_INTERNAL_KEY (the old account-center secret), which the
    collapsed gate does not read as a per-caller key. It must still be accepted as
    a legacy alias — else KBS notify 401s on the first platform recreate."""
    monkeypatch.setenv(ia.LEGACY_ENV_ALT, "archie-internal-alias")
    with caplog.at_level(logging.WARNING, logger="services.internal_auth"):
        r = client.post(
            "/tools/account-center/api/internal/notify",
            headers={"X-Internal-Key": "archie-internal-alias"},
            json={"message": "x"},
        )
    assert r.status_code == 200
    assert any("legacy ARCHIE_INTERNAL_KEY used" in rec.getMessage() for rec in caplog.records)
    # and it dies with the flat key when legacy acceptance is switched off
    monkeypatch.setenv(ia.LEGACY_ACCEPT_ENV, "0")
    assert (
        client.post(
            "/tools/account-center/api/internal/notify",
            headers={"X-Internal-Key": "archie-internal-alias"},
            json={"message": "x"},
        ).status_code
        == 401
    )


def test_watch_can_reach_notify_not_a_dead_scope(client, keys):
    """watch products call /api/internal/notify; the grant must let their own key
    through (the removed `access:check` grant decorated no route)."""
    assert client.post(
        "/api/internal/notify", headers=_bearer(keys["watch"]), json={"message": "x", "priority": "low"}
    ).status_code not in (401, 403)
    # still fenced out of a route it does not call
    assert client.get("/api/internal/mail/inbox", headers=_bearer(keys["watch"])).status_code == 403


def test_legacy_key_is_full_scope_but_loud(client, keys, caplog):
    with caplog.at_level(logging.WARNING, logger="services.internal_auth"):
        r = client.get("/api/internal/repair/count", headers=_bearer(LEGACY))
    assert r.status_code not in (401, 403)
    assert any("legacy INTERNAL_API_KEY used" in rec.getMessage() for rec in caplog.records)


def test_legacy_key_can_be_switched_off(client, keys, monkeypatch):
    monkeypatch.setenv(ia.LEGACY_ACCEPT_ENV, "0")
    assert client.get("/api/internal/repair/count", headers=_bearer(LEGACY)).status_code == 401
    # per-caller keys are unaffected by the switch
    assert client.get("/api/internal/repair/count", headers=_bearer(keys["archie_comms"])).status_code not in (401, 403)


def test_comparison_is_constant_time(monkeypatch, keys):
    """hmac.compare_digest must be the comparator — `==` leaks match length via timing."""
    calls = []
    real = ia.hmac.compare_digest

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(ia.hmac, "compare_digest", spy)
    from app import app as flask_app  # noqa: PLC0415

    with flask_app.test_request_context(headers=_bearer(keys["kbs"])):
        assert ia.identify_caller()[0] == "kbs"
    assert calls, "no constant-time comparison happened"


def test_keys_are_read_at_request_time_not_import_time(client, monkeypatch, keys):
    """Rotation without a restart — the account_center bug was an import-time read."""
    monkeypatch.setenv(ia.CALLER_ENV["scripts"], "rotated-now")
    assert (
        client.post(
            "/api/internal/notify", headers=_bearer("rotated-now"), json={"message": "x", "priority": "low"}
        ).status_code
        == 200
    )
    assert (
        client.post("/api/internal/notify", headers=_bearer(keys["scripts"]), json={"message": "x"}).status_code == 401
    )


def test_compliance_rule_packs_use_the_same_gate(client, keys):
    assert (
        client.get(
            "/tools/security-network/api/compliance/rule-packs", headers={"X-Internal-Key": keys["kso"]}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/tools/security-network/api/compliance/rule-packs", headers={"X-Internal-Key": keys["browser"]}
        ).status_code
        == 401
    )
    assert client.get("/tools/security-network/api/compliance/rule-packs").status_code == 401
