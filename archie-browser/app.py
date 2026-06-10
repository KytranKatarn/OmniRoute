"""archie_browser — Playwright browser automation HTTP API."""
import hmac
import json
import logging
import os
import random
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from flask import Flask, jsonify, request

_API_KEY = os.getenv("BROWSER_API_KEY", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app(testing=False):
    app = Flask(__name__)
    app.config["TESTING"] = testing
    app._tasks: dict = {}
    app._tasks_lock = threading.Lock()
    # Rate limiting: track execution timestamps for human-like pacing
    app._exec_times: deque = deque(maxlen=100)   # rolling window
    app._rate_lock = threading.Lock()
    app._min_delay_s = float(os.getenv("BROWSER_MIN_DELAY_S", "2"))
    app._max_delay_s = float(os.getenv("BROWSER_MAX_DELAY_S", "5"))
    app._max_per_hour = int(os.getenv("BROWSER_MAX_PER_HOUR", "60"))

    # In testing mode inject MagicMock stubs so imports of session_manager /
    # skill_runner inside route handlers are short-circuited by the module cache.
    if testing:
        from unittest.mock import MagicMock
        import sys

        _sm = MagicMock()
        _sm.get_session_status.return_value = {"status": "missing", "last_used": None}
        _sm.setup_session.return_value = {"status": "active"}
        sys.modules["session_manager"] = _sm

        _sr = MagicMock()
        _sr.run.return_value = {}
        _sr.list_skills.return_value = []
        sys.modules["skill_runner"] = _sr

    @app.before_request
    def check_auth():
        # Health endpoint is public for monitoring
        if request.path == "/health":
            return None
        if not _API_KEY:
            return None  # No key configured -- open in dev mode
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth[7:]
        if not hmac.compare_digest(token, _API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return None

    @app.get("/health")
    def health():
        try:
            import skill_runner as _sr
            skills = _sr.list_skills() if hasattr(_sr, "list_skills") else []
        except Exception:
            skills = []
        return jsonify({"status": "ok", "service": "archie_browser", "skills": skills})

    @app.post("/task")
    def post_task():
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        skill_name = data.get("skill")
        params = data.get("params") or {}
        wait = bool(data.get("wait", False))

        if not agent_id or not skill_name:
            return jsonify({"error": "agent_id and skill required"}), 400

        task_id = str(uuid.uuid4())
        with app._tasks_lock:
            app._tasks[task_id] = {
                "status": "pending",
                "result": None,
                "error": None,
                "agent_id": agent_id,
                "skill": skill_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        if wait:
            _execute_task(app, task_id, agent_id, skill_name, params)
        else:
            t = threading.Thread(
                target=_execute_task,
                args=(app, task_id, agent_id, skill_name, params),
                daemon=True,
            )
            t.start()

        with app._tasks_lock:
            return jsonify({"task_id": task_id, "status": app._tasks[task_id]["status"]})

    @app.get("/task/<task_id>")
    def get_task(task_id):
        with app._tasks_lock:
            state = app._tasks.get(task_id)
        if not state:
            return jsonify({"error": "not found"}), 404
        return jsonify({"task_id": task_id, **state})

    @app.get("/session/<int:agent_id>/<platform>")
    def get_session(agent_id, platform):
        try:
            import session_manager
            status = session_manager.get_session_status(agent_id, platform)
            return jsonify(status)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/session/setup")
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
            logger.error("session_setup failed: %s", type(exc).__name__)
            return jsonify({"error": str(exc)}), 500

    @app.post("/session/credentials")
    def session_credentials():
        """Store encrypted login credentials WITHOUT attempting a login (#3953).

        For the persistent-trusted-profile world the actual login is a one-time
        human step in noVNC; a headless login here would just hit the step-up
        wall. This only persists the creds (AES-GCM via BROWSER_ENCRYPTION_KEY)
        for the worker's re-login fallback. No browser is launched.
        """
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        platform = data.get("platform")
        username = data.get("username")
        password = data.get("password")
        if not all([agent_id, platform, username, password]):
            return jsonify({"error": "agent_id, platform, username, password required"}), 400
        try:
            import session_manager
            session_manager.save_credentials(int(agent_id), platform, username, password)
            return jsonify({"stored": True, "platform": platform, "agent_id": int(agent_id)})
        except Exception as exc:
            # Type-only response — raw str(exc) could echo a DB error string
            # (connection/column detail). Full detail goes to the server log.
            logger.error("session_credentials(%s/%s) failed: %s", agent_id, platform, exc)
            return jsonify({"error": f"credential store failed ({type(exc).__name__})"}), 500

    @app.post("/session/<int:agent_id>/<platform>/refresh")
    def refresh_session(agent_id, platform):
        try:
            import session_manager
            result = session_manager.setup_session(agent_id, platform, None, None)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return app


def _apply_rate_limit(app):
    """Enforce human-like pacing: random delay + per-hour cap."""
    now = time.time()
    with app._rate_lock:
        # Drop timestamps older than 1 hour
        cutoff = now - 3600
        while app._exec_times and app._exec_times[0] < cutoff:
            app._exec_times.popleft()
        # Per-hour cap check
        if len(app._exec_times) >= app._max_per_hour:
            oldest = app._exec_times[0]
            wait = max(0, 3600 - (now - oldest))
            logger.warning("[RateLimit] Hour cap reached, waiting %.0fs", wait)
            time.sleep(wait)
        app._exec_times.append(time.time())
    # Human-like random delay between actions
    delay = random.uniform(app._min_delay_s, app._max_delay_s)
    time.sleep(delay)


def _execute_task(app, task_id, agent_id, skill_name, params):
    with app._tasks_lock:
        app._tasks[task_id]["status"] = "running"

    # Rate limiting — skip for health checks / non-browser ops
    if not app.config.get("TESTING"):
        _apply_rate_limit(app)

    start = datetime.now(timezone.utc)
    try:
        import skill_runner
        result = skill_runner.run(agent_id, skill_name, params)
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        with app._tasks_lock:
            app._tasks[task_id].update(
                {"status": "completed", "result": result, "duration_ms": duration_ms}
            )
        _log_task_to_db(task_id, agent_id, skill_name, params, "completed", result, None, duration_ms)
    except Exception as exc:
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        logger.error("task %s failed: %s", task_id, exc)
        with app._tasks_lock:
            app._tasks[task_id].update(
                {"status": "failed", "error": str(exc), "duration_ms": duration_ms}
            )
        _log_task_to_db(task_id, agent_id, skill_name, params, "failed", None, str(exc), duration_ms)


def _log_task_to_db(task_id, agent_id, skill_name, params, status, result, error, duration_ms):
    try:
        import psycopg2
        import psycopg2.extras
        import os

        conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO browser_task_log
                    (agent_id, skill, params, status, result, error_message, duration_ms,
                     triggered_by, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    agent_id,
                    skill_name,
                    psycopg2.extras.Json(params),
                    status,
                    psycopg2.extras.Json(result) if result else None,
                    error,
                    duration_ms,
                    "platform",
                ),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("_log_task_to_db failed (non-fatal): %s", exc)


# Module-level app instance for direct `flask run` / `python app.py` usage.
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4242, debug=False)
