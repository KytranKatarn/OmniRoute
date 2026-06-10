"""C.R.E.E.D. Command — Tenants ops surface (#3945).

E.T.H.O.S.'s workspace view of the multi-tenant C.R.E.E.D. launch: pending org
applications (approve/reject), active tenants (score/freshness/tier), and per-
tenant API keys. The kytran-creed standalone owns the data; these are thin
hub-local proxies authenticated with the shared CREED_INTERNAL_KEY — never the
public CDN hostname, never exposing the key to the browser.
"""

import logging
import os

import requests
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

_CREED_URL = os.getenv("CREED_API_URL", "http://192.168.1.200:8086")
_TIMEOUT = 10


def _headers():
    return {"X-Internal-Key": os.getenv("CREED_INTERNAL_KEY", "")}


def _proxy_get(path):
    r = requests.get(f"{_CREED_URL}{path}", headers=_headers(), timeout=_TIMEOUT)
    return r.json(), r.status_code


def _proxy_post(path, body=None):
    r = requests.post(f"{_CREED_URL}{path}", json=body or {}, headers=_headers(), timeout=_TIMEOUT)
    try:
        return r.json(), r.status_code
    except ValueError:
        return {"success": False, "error": "bad upstream response"}, 502


def register_tenants_routes(bp, admin_required):
    @bp.route("/api/tenants", methods=["GET"])
    @login_required
    @admin_required
    def tenants_list():
        if not os.getenv("CREED_INTERNAL_KEY"):
            return jsonify({"success": False, "error": "CREED_INTERNAL_KEY not configured"}), 503
        try:
            data, status = _proxy_get("/api/internal/tenants")
            return jsonify(data), status
        except Exception as e:
            logger.error("tenants_list proxy failed: %s", e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502

    @bp.route("/api/tenants/applications", methods=["GET"])
    @login_required
    @admin_required
    def tenants_applications():
        try:
            data, status = _proxy_get("/api/internal/applications")
            return jsonify(data), status
        except Exception as e:
            logger.error("tenants_applications proxy failed: %s", e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502

    @bp.route("/api/tenants/<slug>/approve", methods=["POST"])
    @login_required
    @admin_required
    def tenant_approve(slug):
        try:
            data, status = _proxy_post(f"/api/v1/orgs/{slug}/approve")
            return jsonify(data), status
        except Exception as e:
            logger.error("tenant_approve %s proxy failed: %s", slug, e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502

    @bp.route("/api/tenants/<slug>/reject", methods=["POST"])
    @login_required
    @admin_required
    def tenant_reject(slug):
        try:
            data, status = _proxy_post(f"/api/v1/orgs/{slug}/reject")
            return jsonify(data), status
        except Exception as e:
            logger.error("tenant_reject %s proxy failed: %s", slug, e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502

    @bp.route("/api/tenants/<slug>/keys", methods=["GET"])
    @login_required
    @admin_required
    def tenant_keys(slug):
        try:
            data, status = _proxy_get(f"/api/v1/orgs/{slug}/keys")
            return jsonify(data), status
        except Exception as e:
            logger.error("tenant_keys %s proxy failed: %s", slug, e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502

    @bp.route("/api/tenants/<slug>/keys", methods=["POST"])
    @login_required
    @admin_required
    def tenant_mint_key(slug):
        try:
            data, status = _proxy_post(f"/api/v1/orgs/{slug}/keys", request.get_json(silent=True) or {})
            return jsonify(data), status
        except Exception as e:
            logger.error("tenant_mint_key %s proxy failed: %s", slug, e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502
