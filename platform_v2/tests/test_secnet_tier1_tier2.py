"""Full Security Review — Tier-1/Tier-2 fixes for the Security & Network module."""

import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "security_network")


# ---- Tier-2: the get_db_cursor(dict_cursor=True) TypeError is gone ----------
def test_no_dict_cursor_kwarg_remains():
    for fname in ("analytics_routes.py", "vigil_analysis.py"):
        src = open(os.path.join(_MOD, fname)).read()
        assert "dict_cursor=True" not in src, f"{fname} still uses the invalid dict_cursor kwarg"
        assert "get_db_cursor()" in src


# ---- Tier-2: camera-status class-name typo fixed ---------------------------
def test_camera_import_uses_correct_class_name():
    src = open(os.path.join(_MOD, "noc_routes.py")).read()
    assert "HaSurveillanceService" not in src  # the typo'd name is gone
    assert "HASurveillanceService" in src


# ---- Tier-1: ntopng is_healthy fails closed (not a bare 200) ---------------
def test_ntopng_is_healthy_requires_authenticated_json():
    sys.path.insert(0, _MOD)
    import ntopng_service

    svc = ntopng_service.NtopngService.__new__(ntopng_service.NtopngService)
    svc._ensure_auth = lambda: None

    # Not authenticated → unhealthy even if a call would 200.
    svc._authenticated = False
    svc._get = lambda *a, **k: {"rc": 0}
    assert svc.is_healthy() is False

    # Authenticated but HTML/login (the fail-open case): _get returns rc == -1.
    svc._authenticated = True
    svc._get = lambda *a, **k: {"rc": -1}
    assert svc.is_healthy() is False

    # Authenticated JSON success.
    svc._authenticated = True
    svc._get = lambda *a, **k: {"rc": 0, "rsp": []}
    assert svc.is_healthy() is True


# ---- Tier-1: the honest "recommendation" alert type is registered ----------
def test_recommendation_alert_type_registered():
    sys.path.insert(0, _MOD)
    import security_alerts

    assert "recommendation" in security_alerts.VALID_ALERT_TYPES


# ---- Tier-1: auto-block no longer claims a block was executed ---------------
def test_auto_block_alert_is_honest():
    src = open(os.path.join(_MOD, "jobs.py")).read()
    assert "Auto-blocked:" not in src  # the false claim is gone
    assert "Action recommended:" in src
    assert "NOT automatically blocked" in src


# ---- Tier-1: reports viewReport escapes DB fields (XSS) ---------------------
def test_view_report_escapes_db_fields():
    src = open(os.path.join(os.path.dirname(__file__), "..", "static", "js", "security-network-app.js")).read()
    # The escaper is defined and applied to attacker-influenceable fields.
    assert "const esc =" in src
    assert "esc(dev.hostname" in src
    assert "esc(c.domain" in src
    assert "esc(e.description" in src
    # No raw (unescaped) interpolation of those fields remains in the report body.
    assert "+(dev.hostname||'-')+" not in src
    assert "+(e.description||'-')+" not in src
