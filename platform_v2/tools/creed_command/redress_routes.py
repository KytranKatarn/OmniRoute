"""C.R.E.E.D. Command — Redress queue ops surface.

E.T.H.O.S.'s workspace view of the accountability/redress-request queue filed
via creed-ai.org/accountability.html. The kytran-creed standalone owns the
data; these are thin hub-local proxies authenticated with the shared
CREED_INTERNAL_KEY — never the public CDN hostname, never exposing the key
to the browser. Mirrors tenants_routes.py.
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


def register_redress_routes(bp, admin_required):
    @bp.route("/api/redress-requests", methods=["GET"])
    @login_required
    @admin_required
    def redress_list():
        if not os.getenv("CREED_INTERNAL_KEY"):
            return jsonify({"success": False, "error": "CREED_INTERNAL_KEY not configured"}), 503
        try:
            params = {}
            status = request.args.get("status")
            if status:
                params["status"] = status
            r = requests.get(
                f"{_CREED_URL}/api/internal/redress-requests",
                headers=_headers(),
                params=params,
                timeout=_TIMEOUT,
            )
            return jsonify(r.json()), r.status_code
        except Exception as e:
            logger.error("redress_list proxy failed: %s", e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502

    @bp.route("/api/redress-requests/<request_ref>/resolve", methods=["POST"])
    @login_required
    @admin_required
    def redress_resolve(request_ref):
        body = request.get_json(silent=True) or {}
        try:
            r = requests.post(
                f"{_CREED_URL}/api/internal/redress-requests/{request_ref}/resolve",
                json=body,
                headers=_headers(),
                timeout=_TIMEOUT,
            )
            return jsonify(r.json()), r.status_code
        except Exception as e:
            logger.error("redress_resolve %s proxy failed: %s", request_ref, e)
            return jsonify({"success": False, "error": "standalone unreachable"}), 502
