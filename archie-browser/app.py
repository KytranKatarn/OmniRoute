"""archie_browser — Playwright browser automation HTTP API."""
import json
import logging
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_tasks: dict = {}
_tasks_lock = threading.Lock()


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "archie_browser"})


@app.route("/task", methods=["POST"])
def post_task():
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    skill_name = data.get("skill")
    params = data.get("params") or {}
    wait = bool(data.get("wait", False))

    if not agent_id or not skill_name:
        return jsonify({"error": "agent_id and skill required"}), 400

    task_id = str(uuid.uuid4())
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "agent_id": agent_id,
            "skill": skill_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    if wait:
        _execute_task(task_id, agent_id, skill_name, params)
    else:
        t = threading.Thread(
            target=_execute_task, args=(task_id, agent_id, skill_name, params), daemon=True
        )
        t.start()

    with _tasks_lock:
        return jsonify({"task_id": task_id, "status": _tasks[task_id]["status"]})


@app.route("/task/<task_id>")
def get_task(task_id):
    with _tasks_lock:
        state = _tasks.get(task_id)
    if not state:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task_id": task_id, **state})


@app.route("/session/setup", methods=["POST"])
def session_setup():
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    platform = data.get("platform")
    username = data.get("username")
    password = data.get("password")

    if not all([agent_id, platform, username, password]):
        return jsonify({"error": "agent_id, platform, username, password required"}), 400

    try:
        import session_manager
        result = session_manager.setup_session(agent_id, platform, username, password)
        return jsonify(result)
    except Exception as exc:
        logger.error("session_setup failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/session/<int:agent_id>/<platform>")
def get_session(agent_id, platform):
    try:
        import session_manager
        status = session_manager.get_session_status(agent_id, platform)
        return jsonify(status)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _execute_task(task_id, agent_id, skill_name, params):
    with _tasks_lock:
        _tasks[task_id]["status"] = "running"

    start = datetime.now(timezone.utc)
    try:
        import skill_runner
        result = skill_runner.run(agent_id, skill_name, params)
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        with _tasks_lock:
            _tasks[task_id].update({"status": "completed", "result": result, "duration_ms": duration_ms})
        _log_task_to_db(task_id, agent_id, skill_name, params, "completed", result, None, duration_ms)
    except Exception as exc:
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        logger.error("task %s failed: %s", task_id, exc)
        with _tasks_lock:
            _tasks[task_id].update({"status": "failed", "error": str(exc), "duration_ms": duration_ms})
        _log_task_to_db(task_id, agent_id, skill_name, params, "failed", None, str(exc), duration_ms)


def _log_task_to_db(task_id, agent_id, skill_name, params, status, result, error, duration_ms):
    try:
        import psycopg2
        import psycopg2.extras
        import os

        conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO browser_task_log
                (agent_id, skill, params, status, result, error_message, duration_ms,
                 triggered_by, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                agent_id, skill_name,
                psycopg2.extras.Json(params), status,
                psycopg2.extras.Json(result) if result else None,
                error, duration_ms, "platform",
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        logger.warning("_log_task_to_db failed (non-fatal): %s", exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4242, debug=False)
