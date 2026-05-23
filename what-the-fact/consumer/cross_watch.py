"""Cross-Watch proxy routes for WTF consumer.

All requests are forwarded to the hub at CROSS_WATCH_HUB_URL via the
Headscale mesh (http://100.64.0.4:3000) — NEVER the public hostname.

Auth is handled hub-side.  This layer only adds:
  - Authorization: Bearer CROSS_WATCH_SERVICE_TOKEN
  - X-User-Email: <session wtf_email>

Security: this module NEVER forwards CROSS_WATCH_SERVICE_TOKEN to the
browser.  All hub calls are server-to-server only.
"""

import logging
import os

import requests as _req
from flask import Blueprint, jsonify, request, session

logger = logging.getLogger(__name__)

cross_watch_bp = Blueprint("cross_watch", __name__)

_HUB = os.getenv("CROSS_WATCH_HUB_URL", "http://100.64.0.4:3000")
_TOKEN = os.getenv("CROSS_WATCH_SERVICE_TOKEN", "")
_TIMEOUT = 5


def _hub_headers() -> dict:
    email = session.get("wtf_email", "")
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "X-User-Email": email,
        "Content-Type": "application/json",
    }


def _proxy_get(path: str):
    try:
        r = _req.get(f"{_HUB}{path}", headers=_hub_headers(), timeout=_TIMEOUT)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        logger.error("[cross_watch] proxy GET %s failed: %s", path, exc)
        return jsonify({"error": "hub unavailable"}), 503


def _proxy_post(path: str, body: dict | None = None):
    try:
        r = _req.post(
            f"{_HUB}{path}",
            headers=_hub_headers(),
            json=body or request.get_json(silent=True) or {},
            timeout=_TIMEOUT,
        )
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        logger.error("[cross_watch] proxy POST %s failed: %s", path, exc)
        return jsonify({"error": "hub unavailable"}), 503


def _proxy_delete(path: str):
    try:
        r = _req.delete(f"{_HUB}{path}", headers=_hub_headers(), timeout=_TIMEOUT)
        return jsonify(r.json()), r.status_code
    except Exception as exc:
        logger.error("[cross_watch] proxy DELETE %s failed: %s", path, exc)
        return jsonify({"error": "hub unavailable"}), 503


@cross_watch_bp.route("/api/cross-watch/alerts")
def alerts():
    return _proxy_get("/api/cross-watch/alerts")


@cross_watch_bp.route("/api/cross-watch/alerts/<int:alert_id>/read", methods=["POST"])
def mark_read(alert_id: int):
    return _proxy_post(f"/api/cross-watch/alerts/{alert_id}/read")


@cross_watch_bp.route("/api/cross-watch/entities")
def entities():
    return _proxy_get("/api/cross-watch/entities")


@cross_watch_bp.route("/api/cross-watch/follow", methods=["POST"])
def follow():
    return _proxy_post("/api/cross-watch/follow")


@cross_watch_bp.route("/api/cross-watch/follow/<int:entity_id>", methods=["DELETE"])
def unfollow(entity_id: int):
    return _proxy_delete(f"/api/cross-watch/follow/{entity_id}")


@cross_watch_bp.route("/api/cross-watch/following")
def following():
    return _proxy_get("/api/cross-watch/following")


@cross_watch_bp.route("/api/cross-watch/procurement")
def procurement():
    """Proxy: return recent gov_watch tenders matching an article title's entities.
    Passes ?title= and optional ?limit= through to hub. No user session required.
    """
    import urllib.parse

    title = request.args.get("title", "")
    limit = request.args.get("limit", "5")
    qs = urllib.parse.urlencode({"title": title, "limit": limit})
    return _proxy_get(f"/api/cross-watch/procurement?{qs}")
