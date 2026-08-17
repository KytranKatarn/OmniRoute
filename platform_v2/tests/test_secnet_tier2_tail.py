"""Full Security Review — Tier-2 tail (Security & Network): device tab, traffic,
domain list, exception-leak hardening, duplicate DOM IDs."""

import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "security_network")
_TPL = os.path.join(os.path.dirname(__file__), "..", "templates", "tools", "security_network.html")
_JSF = os.path.join(os.path.dirname(__file__), "..", "static", "js", "security-network-features.js")


def _src(p):
    return open(p).read()


# ---- Devices tab: 3 broken controls repaired -------------------------------
def test_device_add_mapping_accepts_ui_keys():
    s = _src(os.path.join(_MOD, "device_routes.py"))
    assert 'data.get("mac_address") or data.get("mac")' in s
    assert 'data.get("user_name") or data.get("username")' in s
    assert 'data.get("device_label") or data.get("device_name")' in s


def test_device_type_filter_accepts_type_param():
    s = _src(os.path.join(_MOD, "device_registry_routes.py"))
    assert 'request.args.get("device_type") or request.args.get("type")' in s


def test_device_edit_passes_kwargs_not_positional_dict():
    s = _src(os.path.join(_MOD, "device_registry_routes.py"))
    assert "device_registry.update_device(device_id, **data)" in s
    assert "device_registry.update_device(device_id, data)" not in s


# ---- Traffic history: real columns + valid interval + dict rows ------------
def test_traffic_history_uses_real_columns_and_interval():
    s = _src(os.path.join(_MOD, "traffic_routes.py"))
    assert "make_interval(hours => %s)" in s
    assert "SUM(bytes_out)" in s and "SUM(bytes_in)" in s
    assert 'row["device_mac"]' in s  # dict access, not row[0]
    # the broken interval placeholder is gone from the code
    assert "INTERVAL '%s hours'" not in s
    # 24h bandwidth totals now read aliased columns by name (row[0] KeyError'd)
    assert 'row["total_in"]' in s


# ---- Domain list/records: no column-names-as-values bug --------------------
def test_domain_routes_use_dict_rows():
    s = _src(os.path.join(_MOD, "domain_npm_routes.py"))
    assert "= dict(zip(cols" not in s  # the buggy assignment is gone
    assert "d = dict(r)" in s
    assert "rec = dict(r)" in s


# ---- Exception-leak hardening: no raw str(exc) in responses ----------------
def test_no_raw_exception_leaked_to_client():
    for f in ("incident_routes.py", "supervision_routes.py", "noc_routes.py"):
        s = _src(os.path.join(_MOD, f))
        assert '"error": str(exc)' not in s, f"{f} still leaks the exception text"


# ---- Duplicate DOM IDs resolved --------------------------------------------
def test_dns_stat_ids_unique():
    tpl = _src(_TPL)
    assert tpl.count('id="dns-blocked"') == 1
    assert tpl.count('id="dns-top-blocked"') == 1
    assert 'id="rpt-dns-blocked"' in tpl
    js = _src(_JSF)
    assert "getElementById('rpt-dns-blocked')" in js
    assert "getElementById('rpt-dns-top-blocked')" in js
