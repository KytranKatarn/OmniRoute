"""mesh.kytranempowerment.com must never point at a host with no TLS listener (#5219).

INCIDENT 2026-07-26. During hub recovery all 15 AdGuard rewrites were repointed to
192.168.1.200 as a batch. One of them was mesh. — the Headscale CONTROL PLANE, which
is TLS-only. The recovery hub Caddy was HTTP-only, so the control plane became
unreachable and BOTH LAN Starships dropped off the mesh. Reverting that single
rewrite to Beacon brought them back in ~2 minutes.

The owner had flagged it in advance ("wasnt this on beacon ?") and the question was
answered in general terms without checking that specific hostname. A categorical
answer cannot discharge a specific warning — hence a machine-checked rule.
"""

import socket
import threading

import pytest

from tools.security_network.adguard_service import (
    PROTECTED_REWRITES,
    ProtectedRewriteError,
    check_rewrite_allowed,
)

MESH = "mesh.kytranempowerment.com"


@pytest.fixture
def tls_like_listener():
    """A host that IS listening — stands in for Beacon serving 443."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.close()
            except Exception:
                continue

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    yield port
    stop.set()
    t.join(timeout=2)
    srv.close()


def test_mesh_is_a_protected_hostname():
    assert MESH in PROTECTED_REWRITES
    assert 443 in PROTECTED_REWRITES[MESH]["required_ports"]


def test_repointing_mesh_at_a_host_with_no_tls_listener_is_refused(monkeypatch):
    """THE INCIDENT, reproduced.

    The hub during recovery ran an HTTP-only Caddy — nothing on 443. Repointing
    mesh. at it is exactly the change that severed the mesh.
    """
    import services.node_reachability as nr

    monkeypatch.setattr(nr, "probe_node", lambda h, p=None, timeout=3.0: nr.Reachability(False, None, None))

    allowed, reason = check_rewrite_allowed(MESH, "192.168.1.200")
    assert allowed is False
    assert "443" in reason
    assert "control plane" in reason.lower()


def test_repointing_mesh_at_a_host_that_does_serve_tls_is_allowed(tls_like_listener):
    """Beacon serves 443 — that repoint is the CORRECT one and must not be blocked."""
    rule = PROTECTED_REWRITES[MESH]
    original = rule["required_ports"]
    rule["required_ports"] = (tls_like_listener,)
    try:
        allowed, reason = check_rewrite_allowed(MESH, "127.0.0.1")
        assert allowed is True
        assert reason is None
    finally:
        rule["required_ports"] = original


def test_unprotected_hostnames_are_untouched():
    """The guard must not turn every DNS edit into a reachability negotiation.

    The bulk repoint of the other 14 rewrites was correct and necessary.
    """
    allowed, reason = check_rewrite_allowed("plex.kytranempowerment.com", "192.168.1.200")
    assert allowed is True
    assert reason is None


def test_domain_matching_is_case_and_trailing_dot_insensitive(monkeypatch):
    """A guard that a different spelling walks straight past is not a guard."""
    import services.node_reachability as nr

    monkeypatch.setattr(nr, "probe_node", lambda h, p=None, timeout=3.0: nr.Reachability(False, None, None))

    for spelling in (MESH.upper(), MESH + ".", "  " + MESH + "  "):
        allowed, _ = check_rewrite_allowed(spelling, "192.168.1.200")
        assert allowed is False, f"guard bypassed by spelling {spelling!r}"


def test_empty_target_is_refused_for_protected_hostname():
    allowed, reason = check_rewrite_allowed(MESH, "")
    assert allowed is False
    assert reason


def test_add_rewrite_raises_with_the_reason_attached(monkeypatch):
    """The refusal must carry WHY — a generic failure is how this got missed."""
    import services.node_reachability as nr
    from tools.security_network.adguard_service import AdGuardService

    monkeypatch.setattr(nr, "probe_node", lambda h, p=None, timeout=3.0: nr.Reachability(False, None, None))

    svc = AdGuardService()
    with pytest.raises(ProtectedRewriteError) as exc:
        svc.add_rewrite(MESH, "192.168.1.200")

    assert exc.value.domain == MESH
    assert exc.value.answer == "192.168.1.200"
    assert "443" in exc.value.reason


def test_force_is_an_explicit_override(monkeypatch):
    """An operator who knows the target is about to listen can still proceed."""
    import services.node_reachability as nr
    from tools.security_network.adguard_service import AdGuardService

    monkeypatch.setattr(nr, "probe_node", lambda h, p=None, timeout=3.0: nr.Reachability(False, None, None))

    svc = AdGuardService()
    calls = {}

    def _fake_request(method, endpoint, data=None, params=None, timeout=10):
        calls["endpoint"] = endpoint
        return {"ok": True}

    monkeypatch.setattr(svc, "_request", _fake_request)

    assert svc.add_rewrite(MESH, "192.168.1.200", force=True) == {"ok": True}
    assert calls["endpoint"] == "rewrite/add"
