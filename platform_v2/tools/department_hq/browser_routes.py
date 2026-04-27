"""Platform proxy routes for archie_browser container.

POST /api/browser/task      — validate agent is internal, forward to archie_browser
GET  /api/browser/task/:id  — poll archie_browser for result
GET  /api/browser/health    — check archie_browser availability
"""

import logging
import os

import requests as _req
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

browser_bp = Blueprint("browser", __name__)

_BROWSER_URL = os.getenv("ARCHIE_BROWSER_URL", "http://archie_browser:4242")


@browser_bp.route("/api/browser/task", methods=["POST"])
def api_browser_task():
    """Submit a browser task. Validates agent is internal (not AI)."""
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    skill = data.get("skill")
    params = data.get("params") or {}

    if not agent_id or not skill:
        return jsonify({"error": "agent_id and skill required"}), 400

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT worker_type FROM agents WHERE id = %s", (agent_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Agent not found"}), 404
            if row["worker_type"] != "internal":
                return jsonify({"error": "Browser tasks are for internal agents only"}), 403
    except Exception as exc:
        logger.error("browser task agent check failed: %s", exc)
        return jsonify({"error": "DB check failed"}), 500

    try:
        resp = _req.post(
            f"{_BROWSER_URL}/task",
            json={"agent_id": agent_id, "skill": skill, "params": params},
            timeout=30,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as exc:
        logger.error("archie_browser /task call failed: %s", exc)
        return jsonify({"error": "Browser container unavailable", "detail": str(exc)}), 503


@browser_bp.route("/api/browser/task/<task_id>")
def api_browser_task_status(task_id):
    """Poll task status from archie_browser."""
    try:
        resp = _req.get(f"{_BROWSER_URL}/task/{task_id}", timeout=10)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@browser_bp.route("/api/browser/health")
def api_browser_health():
    """Check archie_browser availability."""
    try:
        resp = _req.get(f"{_BROWSER_URL}/health", timeout=5)
        resp.raise_for_status()
        return jsonify({"status": "ok", "browser_url": _BROWSER_URL})
    except Exception as exc:
        return jsonify({"status": "unavailable", "error": str(exc)}), 503
