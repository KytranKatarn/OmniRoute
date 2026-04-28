"""Platform proxy routes for archie_browser container — Browser Persona System.

POST /api/browser/task                    — submit task (logs to browser_task_log)
GET  /api/browser/task/<task_id>          — poll task status from container
GET  /api/browser/sessions/<agent_id>     — list browser sessions for agent
POST /api/browser/sessions/<agent_id>/setup — set up platform session
GET  /api/browser/skills                  — list available browser skills
GET  /api/browser/task-log                — platform-side task history

Project #287 — Browser Persona System (Task 11)
"""

import logging
import os

import psycopg2.extras
import requests as _req
from database import get_db_cursor
from flask import jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Container URL resolution
# ---------------------------------------------------------------------------

_BROWSER_URLS = {
    "hub": os.getenv("ARCHIE_BROWSER_URL", "http://archie_browser:4242"),
    "outpost-us": os.getenv("ARCHIE_BROWSER_URL_OUTPOST_US", "http://76.13.107.109:4242"),
}

_BROWSER_API_KEY = os.getenv("BROWSER_API_KEY", "")


def _get_browser_url(agent_id: int) -> str:
    """Look up agent's preferred_node, resolve to container URL."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT preferred_node FROM agent_online_persona WHERE agent_id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
    node = row["preferred_node"] if row and row.get("preferred_node") else "hub"
    return _BROWSER_URLS.get(node, _BROWSER_URLS["hub"])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _log_task(cur, agent_id, skill, platform, params, triggered_by) -> int:
    cur.execute(
        """INSERT INTO browser_task_log
               (agent_id, skill, platform, params, status, triggered_by, created_at)
           VALUES (%s, %s, %s, %s, 'pending', %s, NOW()) RETURNING id""",
        (
            agent_id,
            skill,
            platform,
            psycopg2.extras.Json(params) if params is not None else None,
            triggered_by,
        ),
    )
    return cur.fetchone()["id"]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_browser_routes(bp, admin_required):
    """Register Browser Persona System proxy routes on the blueprint."""

    # ── Submit task ───────────────────────────────────────────────────────

    @bp.route("/api/browser/task", methods=["POST"])
    @admin_required
    def browser_submit_task():
        """Validate agent is internal, log task, forward to archie_browser container."""
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        skill = data.get("skill")
        params = data.get("params") or {}
        triggered_by = data.get("triggered_by")

        if not agent_id or not skill:
            return jsonify({"error": "agent_id and skill required"}), 400

        # Verify agent exists and is internal
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT worker_type FROM agents WHERE id = %s", (agent_id,))
                row = cur.fetchone()
        except Exception as exc:
            logger.error("browser task agent lookup failed: %s", type(exc).__name__)
            return jsonify({"error": "DB error during agent check"}), 500

        if not row:
            return jsonify({"error": "Agent not found"}), 404
        if row["worker_type"] != "internal":
            return jsonify({"error": "Browser tasks are for internal agents only"}), 403

        platform = params.get("platform") if isinstance(params, dict) else None

        # Log task as pending
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                log_id = _log_task(cur, agent_id, skill, platform, params, triggered_by)
        except Exception as exc:
            logger.error("browser task log insert failed: %s", type(exc).__name__)
            return jsonify({"error": "Failed to log task"}), 500

        # Forward to container
        browser_url = _get_browser_url(agent_id)
        try:
            resp = _req.post(
                f"{browser_url}/task",
                json={"agent_id": agent_id, "skill": skill, "params": params},
                headers={"Authorization": f"Bearer {_BROWSER_API_KEY}"},
                timeout=30,
            )
            resp.raise_for_status()
            container_data = resp.json()
            task_id = container_data.get("task_id")

            # Update log to running
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE browser_task_log SET status = 'running', task_id = %s WHERE id = %s",
                    (task_id, log_id),
                )

            return jsonify({"task_id": task_id, "log_id": log_id, "status": "running"})

        except Exception as exc:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE browser_task_log SET status='failed', error_message=%s WHERE id=%s",
                    (str(exc)[:500], log_id),
                )
            logger.error("submit_browser_task: container unreachable: %s", type(exc).__name__)
            return jsonify({"error": "Container unreachable"}), 502

    # ── Poll task status ──────────────────────────────────────────────────

    @bp.route("/api/browser/task/<task_id>")
    @admin_required
    def browser_task_status(task_id):
        """Poll task status from archie_browser container."""
        # Allow caller to specify node, default to hub
        node = request.args.get("node", "hub")
        url = _BROWSER_URLS.get(node, _BROWSER_URLS["hub"])
        try:
            resp = _req.get(
                f"{url}/task/{task_id}", headers={"Authorization": f"Bearer {_BROWSER_API_KEY}"}, timeout=10
            )
            if resp.status_code == 404:
                return jsonify({"error": "Task not found"}), 404
            resp.raise_for_status()
            return jsonify(resp.json())
        except Exception as exc:
            logger.error("browser task poll failed: %s", type(exc).__name__)
            return jsonify({"error": "Browser container unavailable"}), 502

    # ── List sessions for agent ───────────────────────────────────────────

    @bp.route("/api/browser/sessions/<int:agent_id>")
    @admin_required
    def browser_list_sessions(agent_id):
        """List browser sessions for the given agent."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT platform, status, username, last_used, expires_at
                         FROM agent_browser_sessions
                        WHERE agent_id = %s
                        ORDER BY last_used DESC NULLS LAST""",
                    (agent_id,),
                )
                sessions = []
                for row in cur.fetchall():
                    s = dict(row)
                    s["last_used"] = s["last_used"].isoformat() if s["last_used"] else None
                    s["expires_at"] = s["expires_at"].isoformat() if s["expires_at"] else None
                    sessions.append(s)
            return jsonify({"agent_id": agent_id, "sessions": sessions})
        except Exception as exc:
            logger.error("browser sessions query failed: %s", type(exc).__name__)
            return jsonify({"error": "DB error"}), 500

    # ── Set up a session ──────────────────────────────────────────────────

    @bp.route("/api/browser/sessions/<int:agent_id>/setup", methods=["POST"])
    @admin_required
    def browser_setup_session(agent_id):
        """Forward session setup credentials to archie_browser container."""
        data = request.get_json(silent=True) or {}
        platform = data.get("platform")
        username = data.get("username")
        password = data.get("password")

        if not platform or not username or not password:
            return jsonify({"error": "platform, username and password required"}), 400

        browser_url = _get_browser_url(agent_id)
        try:
            resp = _req.post(
                f"{browser_url}/session/setup",
                json={
                    "agent_id": agent_id,
                    "platform": platform,
                    "username": username,
                    "password": password,
                },
                headers={"Authorization": f"Bearer {_BROWSER_API_KEY}"},
                timeout=60,
            )
            resp.raise_for_status()
            return jsonify(resp.json())
        except Exception as exc:
            logger.error("browser session setup forward failed: %s", type(exc).__name__)
            return jsonify({"error": "Browser container unavailable"}), 502

    # ── List available skills ─────────────────────────────────────────────

    @bp.route("/api/browser/skills")
    @admin_required
    def browser_list_skills():
        """Return skill list from archie_browser /health endpoint."""
        hub_url = _BROWSER_URLS["hub"]
        try:
            resp = _req.get(f"{hub_url}/health", timeout=5)  # /health is public, no auth needed
            resp.raise_for_status()
            data = resp.json()
            return jsonify({"skills": data.get("skills", [])})
        except Exception as exc:
            logger.error("browser skills fetch failed: %s", type(exc).__name__)
            return jsonify({"error": "Browser container unavailable", "skills": []}), 502

    # ── Task log (platform-side) ──────────────────────────────────────────

    @bp.route("/api/browser/task-log")
    @admin_required
    def browser_task_log():
        """Platform-side browser task history, optionally filtered by agent."""
        agent_id = request.args.get("agent_id", type=int)
        limit = min(request.args.get("limit", 50, type=int), 200)

        try:
            with get_db_cursor() as (conn, cur):
                if agent_id:
                    cur.execute(
                        """SELECT btl.*, a.display_name AS agent_name
                             FROM browser_task_log btl
                             LEFT JOIN agents a ON a.id = btl.agent_id
                            WHERE btl.agent_id = %s
                            ORDER BY btl.created_at DESC
                            LIMIT %s""",
                        (agent_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT btl.*, a.display_name AS agent_name
                             FROM browser_task_log btl
                             LEFT JOIN agents a ON a.id = btl.agent_id
                            ORDER BY btl.created_at DESC
                            LIMIT %s""",
                        (limit,),
                    )

                tasks = []
                for row in cur.fetchall():
                    t = dict(row)
                    t["created_at"] = t["created_at"].isoformat() if t["created_at"] else None
                    t["updated_at"] = t["updated_at"].isoformat() if t.get("updated_at") else None
                    tasks.append(t)

                cur.execute(
                    "SELECT COUNT(*) AS total FROM browser_task_log" + (" WHERE agent_id = %s" if agent_id else ""),
                    (agent_id,) if agent_id else (),
                )
                total = cur.fetchone()["total"]

            return jsonify({"tasks": tasks, "total": total})
        except Exception as exc:
            logger.error("browser task-log query failed: %s", type(exc).__name__)
            return jsonify({"error": "DB error"}), 500


# Standalone Blueprint for direct registration in app.py
from flask import Blueprint as _Blueprint

browser_bp = _Blueprint("browser", __name__)
register_browser_routes(browser_bp, lambda f: f)  # no auth_required for internal routes
