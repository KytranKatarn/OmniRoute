"""Full Security Review — Tier-2 broken-control fixes (Security & Network)."""

import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "security_network")
sys.path.insert(0, _MOD)


def _src(fname):
    return open(os.path.join(_MOD, fname)).read()


# ---- Contract fixes: bare array -> {success, <collection>} ------------------
def test_incidents_returns_object_shape():
    s = _src("incident_routes.py")
    assert '"incidents": [dict(r) for r in incidents]' in s
    assert "return jsonify([dict(r) for r in incidents])" not in s


def test_supervision_schedules_returns_object_shape():
    s = _src("supervision_routes.py")
    assert '"schedules": [dict(r) for r in schedules]' in s
    assert "return jsonify([dict(r) for r in schedules])" not in s


# ---- Hostinger DNS: routes now call methods that exist ----------------------
def test_hostinger_service_has_the_methods_the_routes_call():
    import hostinger_service

    svc = hostinger_service.HostingerService()
    assert hasattr(svc, "update_dns_records_bulk")
    assert hasattr(svc, "delete_dns_records")


def test_hostinger_routes_call_existing_methods():
    s = _src("hostinger_routes.py")
    assert "update_dns_records_bulk(" in s
    # the non-existent method name must be gone
    assert "hostinger_service.update_dns_records(" not in s


def test_hostinger_delete_is_filtered_not_whole_zone():
    import hostinger_service

    captured = {}
    svc = hostinger_service.HostingerService()
    svc._request = lambda method, endpoint, data=None, timeout=15: captured.update(
        {"method": method, "endpoint": endpoint, "data": data}
    )
    svc.delete_dns_records("A", "test", "example.com")
    assert captured["method"] == "DELETE"
    assert "example.com" in captured["endpoint"]
    assert captured["data"] == {"filters": [{"name": "test", "type": "A"}]}


# ---- DDNS get_ip_history no longer returns column-names-as-values -----------
def test_ddns_query_uses_dict_rows():
    s = _src("ddns_service.py")
    assert "return [dict(zip(columns" not in s  # the buggy code line is gone
    assert "return [dict(r) for r in cur.fetchall()]" in s


# ---- AdGuard filter toggle sends the full set_url payload ------------------
def test_adguard_toggle_filter_sends_full_data():
    import adguard_service

    captured = {}
    svc = adguard_service.AdGuardService.__new__(adguard_service.AdGuardService)
    svc.get_filtering_status = lambda: {"filters": [{"url": "http://x/list.txt", "name": "My List"}]}
    svc._request = lambda method, endpoint, data=None: captured.update(
        {"method": method, "endpoint": endpoint, "data": data}
    )
    svc.toggle_filter("http://x/list.txt", False)
    assert captured["endpoint"] == "filtering/set_url"
    assert captured["data"]["url"] == "http://x/list.txt"
    assert captured["data"]["whitelist"] is False
    assert captured["data"]["data"] == {"enabled": False, "name": "My List", "url": "http://x/list.txt"}


# ---- The missing domains/certificates route now exists ---------------------
def test_domains_certificates_route_added():
    s = _src("domain_npm_routes.py")
    assert "/api/domains/certificates" in s
    assert "get_ssl_monitors" in s
