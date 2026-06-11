import os, sys
from contextlib import contextmanager
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import proxy_selector
from proxy_selector import resolve_session_egress, select_egress


def _fake_db(fetch_results):
    """Build a get_db replacement whose cursor.fetchone() returns each queued
    dict in turn. fetch_results is a list of dict|None."""
    results = list(fetch_results)
    cur = MagicMock()
    cur.fetchone.side_effect = lambda: results.pop(0) if results else None

    @contextmanager
    def _cursor_cm():
        yield cur

    conn = MagicMock()
    conn.cursor.side_effect = _cursor_cm

    @contextmanager
    def _db_cm():
        yield conn

    return lambda: _db_cm()


def test_gc_ca_routes_to_tier1():
    assert select_egress("https://canadabuys.canada.ca/en/tenders") == 1


def test_canada_ca_routes_to_tier1():
    assert select_egress("https://open.canada.ca/data") == 1


def test_explicit_tier_overrides_domain():
    assert select_egress("https://canadabuys.canada.ca/tenders", requested_tier=2) == 2


def test_unknown_domain_defaults_to_tier1():
    assert select_egress("https://httpbin.org/get") == 1


def test_gouv_qc_routes_to_tier1():
    assert select_egress("https://seao.ca/openweb/index.do") == 1


# ── #4007 resolve_session_egress ──────────────────────────────────────

def test_egress_hub_pref_returns_none(monkeypatch):
    # session egress_pref = 'hub' → hub direct (None), no node lookup
    monkeypatch.setattr(proxy_selector, "get_db", _fake_db([{"egress_pref": "hub"}]))
    assert resolve_session_egress(342, "linkedin") is None


def test_egress_no_pref_returns_none(monkeypatch):
    monkeypatch.setattr(proxy_selector, "get_db", _fake_db([{"egress_pref": None}]))
    assert resolve_session_egress(342, "linkedin") is None


def test_egress_pref_resolves_to_socks(monkeypatch):
    # pref names a node; node lookup returns an online egress-ready mesh_ip
    monkeypatch.setattr(
        proxy_selector,
        "get_db",
        _fake_db([{"egress_pref": "Outpost - United Kingdom"}, {"mesh_ip": "100.64.0.8"}]),
    )
    monkeypatch.setattr(proxy_selector, "_SOCKS_USER", "", raising=False)
    monkeypatch.setattr(proxy_selector, "_SOCKS_PASS", "", raising=False)
    assert resolve_session_egress(342, "linkedin") == "socks5://100.64.0.8:1080"


def test_egress_pref_with_auth(monkeypatch):
    monkeypatch.setattr(
        proxy_selector,
        "get_db",
        _fake_db([{"egress_pref": "Outpost - Singapore"}, {"mesh_ip": "100.64.0.5"}]),
    )
    monkeypatch.setattr(proxy_selector, "_SOCKS_USER", "scout", raising=False)
    monkeypatch.setattr(proxy_selector, "_SOCKS_PASS", "secret", raising=False)
    assert resolve_session_egress(342, "x") == "socks5://scout:secret@100.64.0.5:1080"


def test_egress_offline_node_falls_back_to_hub(monkeypatch):
    # pref names a node but the node lookup finds nothing (offline/unready) → hub
    monkeypatch.setattr(
        proxy_selector,
        "get_db",
        _fake_db([{"egress_pref": "Outpost - Lithuania"}, None]),
    )
    assert resolve_session_egress(342, "linkedin") is None


def test_egress_explicit_node_wins(monkeypatch):
    # explicit_node bypasses the session lookup entirely
    monkeypatch.setattr(proxy_selector, "get_db", _fake_db([{"mesh_ip": "100.64.0.2"}]))
    monkeypatch.setattr(proxy_selector, "_SOCKS_USER", "", raising=False)
    monkeypatch.setattr(proxy_selector, "_SOCKS_PASS", "", raising=False)
    assert resolve_session_egress(1, "claude", "Outpost - United States") == "socks5://100.64.0.2:1080"


def test_egress_db_error_falls_back_to_hub(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(proxy_selector, "get_db", _boom)
    assert resolve_session_egress(342, "linkedin") is None
