"""#5959 — LAN-origin OAuth client selection for on-hub browser QA.

WHY THIS EXISTS: the cockpit's OAuth client is pinned to
https://archie.kytranempowerment.com. From ON the hub, AdGuard split-horizon
resolves that name to 192.168.1.200, which has NO :443 listener (NPM was
decommissioned; Beacon is the front door). The SSO hop dies with
ERR_CONNECTION_REFUSED, so the cockpit could not be browser-tested locally —
which is exactly how the Skills rail (#5334) shipped with zero DOM verification.

THE SAFETY PROPERTY, and the reason the branch is keyed on the REQUEST HOST
rather than a feature flag: a public hostname cannot match a private-IPv4
pattern, so the production login path is untakeable by construction — not
merely "off by default".
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import kytran_auth as ka


# ---------------------------------------------------------------- the predicate


def test_public_hostnames_are_NEVER_lan():
    """The whole safety argument. If this ever fails, production login is at risk."""
    for host in (
        "archie.kytranempowerment.com",
        "platform.kytranempowerment.com",
        "claude.kytranempowerment.com",
        "what-the-fact.com",
        "kytranempowerment.com",
        "",
    ):
        assert not ka._is_lan_host(host), f"{host!r} must NOT be treated as LAN"


def test_private_and_mesh_origins_are_lan():
    for host in (
        "192.168.1.200",      # hub LAN
        "127.0.0.1",
        "localhost",
        "10.1.2.3",
        "172.16.0.9",
        "172.31.255.254",
        "100.64.0.4",         # Headscale mesh (hub)
        "100.127.0.1",        # top of the 100.64.0.0/10 range
    ):
        assert ka._is_lan_host(host), f"{host!r} must be treated as LAN"


def test_lookalikes_outside_the_private_ranges_are_not_lan():
    """172.32 and 100.128 are PUBLIC — a sloppy regex would swallow them."""
    for host in ("172.32.0.1", "172.15.0.1", "100.128.0.1", "100.63.255.255", "11.0.0.1"):
        assert not ka._is_lan_host(host), f"{host!r} is public and must not match"


# ---------------------------------------------------------------- selection


class _SDK(ka.KytranAuth if hasattr(ka, "KytranAuth") else object):
    pass


def _sdk(monkeypatch, host, lan_id="archie-comms-lan", lan_uri="http://192.168.1.200:3002/auth/kytran/callback"):
    obj = ka.KytranAuth() if hasattr(ka, "KytranAuth") else type("S", (), {})()
    obj.client_id, obj.client_secret = "archie-comms", "public-secret"
    obj.redirect_uri = "https://archie.kytranempowerment.com/auth/kytran/callback"
    for k, v in (("KYTRAN_LAN_CLIENT_ID", lan_id), ("KYTRAN_LAN_REDIRECT_URI", lan_uri)):
        monkeypatch.setenv(k, v) if v else monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ka, "request", type("R", (), {"host": host})())
    return obj


def test_public_origin_gets_the_PUBLIC_client_even_when_lan_is_configured(monkeypatch):
    sdk = _sdk(monkeypatch, "archie.kytranempowerment.com")
    cid, _sec, uri = ka.KytranAuth.client_for_request(sdk)
    assert cid == "archie-comms"
    assert uri == "https://archie.kytranempowerment.com/auth/kytran/callback"


def test_lan_origin_gets_the_LAN_client(monkeypatch):
    sdk = _sdk(monkeypatch, "192.168.1.200:3002")
    monkeypatch.setenv("KYTRAN_LAN_CLIENT_SECRET", "lan-secret")
    cid, sec, uri = ka.KytranAuth.client_for_request(sdk)
    assert cid == "archie-comms-lan"
    assert sec == "lan-secret"
    assert uri == "http://192.168.1.200:3002/auth/kytran/callback"


def test_without_the_lan_env_behaviour_is_byte_identical(monkeypatch):
    """Unset env -> the previous code path, even on a LAN origin."""
    sdk = _sdk(monkeypatch, "192.168.1.200:3002", lan_id=None, lan_uri=None)
    monkeypatch.delenv("KYTRAN_LAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("KYTRAN_LAN_REDIRECT_URI", raising=False)
    cid, sec, uri = ka.KytranAuth.client_for_request(sdk)
    assert (cid, sec, uri) == ("archie-comms", "public-secret",
                               "https://archie.kytranempowerment.com/auth/kytran/callback")


def test_lan_secret_falls_back_to_the_public_secret_when_unset(monkeypatch):
    sdk = _sdk(monkeypatch, "10.0.0.5")
    monkeypatch.delenv("KYTRAN_LAN_CLIENT_SECRET", raising=False)
    cid, sec, _uri = ka.KytranAuth.client_for_request(sdk)
    assert cid == "archie-comms-lan" and sec == "public-secret"
