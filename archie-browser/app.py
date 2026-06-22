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
    # Rate limiting: per-PROFILE token bucket (bucket mode, default) replaces the
    # global sleep-under-lock per-hour cap that serialized ALL profiles and was the
    # mechanism behind the 2-day timeout cascade (#4372 family). One saturated profile
    # now returns a NON-BLOCKING rate_limited status instead of stalling the fleet.
    # Legacy global behaviour kept for instant rollback via BROWSER_RATE_LIMIT_MODE=legacy.
    app._exec_times: deque = deque(maxlen=100)   # legacy-mode rolling window
    app._rate_lock = threading.Lock()
    app._profile_buckets: dict = {}              # bucket-mode: key -> _TokenBucket
    app._rate_mode = os.getenv("BROWSER_RATE_LIMIT_MODE", "bucket").lower()
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
        # S6-P1-8b: optional caller idempotency key (content+account+slot hash) +
        # post_metadata, recorded in browser_task_log so a timed-out publish is
        # recoverable + a retry cannot double-post.
        idempotency_key = data.get("idempotency_key")
        post_metadata = data.get("post_metadata")

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
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        if wait:
            _execute_task(app, task_id, agent_id, skill_name, params, idempotency_key, post_metadata)
        else:
            t = threading.Thread(
                target=_execute_task,
                args=(app, task_id, agent_id, skill_name, params, idempotency_key, post_metadata),
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


class RateLimitError(Exception):
    """Raised when a profile's hourly cap is exhausted. NON-BLOCKING — the caller
    surfaces task status='rate_limited' (the platform reschedules) instead of the
    sidecar sleeping under a global lock (the old per-hour cascade)."""

    def __init__(self, retry_after_s: float):
        self.retry_after_s = float(retry_after_s)
        super().__init__(f"rate_limited; retry after {self.retry_after_s:.0f}s")


class _TokenBucket:
    """Per-key token bucket. ``capacity`` tokens, refilled continuously at
    capacity/3600 tokens/sec so the steady-state ceiling == BROWSER_MAX_PER_HOUR per
    key. Starts full. ``consume()`` returns None on admit, or the seconds until enough
    tokens refill on reject. Time is injected so it is deterministically testable."""

    __slots__ = ("capacity", "refill_per_sec", "tokens", "last")

    def __init__(self, capacity: float, now: float):
        self.capacity = float(capacity)
        self.refill_per_sec = (float(capacity) / 3600.0) if capacity > 0 else 0.0
        self.tokens = float(capacity)
        self.last = now

    def consume(self, now: float, amount: float = 1.0):
        if self.refill_per_sec > 0:
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill_per_sec)
        self.last = now
        if self.tokens >= amount:
            self.tokens -= amount
            return None
        if self.refill_per_sec <= 0:
            return 3600.0  # non-positive cap edge — back off an hour
        return (amount - self.tokens) / self.refill_per_sec


def _apply_rate_limit_legacy(app):
    """Original global per-hour cap — kept for BROWSER_RATE_LIMIT_MODE=legacy rollback.
    NOTE: the per-hour wait sleeps UNDER the global lock and serializes all profiles."""
    now = time.time()
    with app._rate_lock:
        cutoff = now - 3600
        while app._exec_times and app._exec_times[0] < cutoff:
            app._exec_times.popleft()
        if len(app._exec_times) >= app._max_per_hour:
            oldest = app._exec_times[0]
            wait = max(0, 3600 - (now - oldest))
            logger.warning("[RateLimit] Hour cap reached, waiting %.0fs", wait)
            time.sleep(wait)
        app._exec_times.append(time.time())
    delay = random.uniform(app._min_delay_s, app._max_delay_s)
    if delay > 0:
        time.sleep(delay)


def _apply_rate_limit(app, key):
    """Per-PROFILE pacing. Default 'bucket' mode: a per-key token bucket admits
    immediately or raises RateLimitError(retry_after_s) — NON-BLOCKING, so one
    saturated profile never serializes the others (the #4372-family cascade fix).
    The human-pacing 2-5s delay runs OUTSIDE the lock, per task. 'legacy' mode
    restores the old global cap (BROWSER_RATE_LIMIT_MODE=legacy).

    ``key`` = the browser identity (agent_id) — one agent == one persistent profile;
    company/creed accounts ride a major's session (same agent_id) and correctly share
    its budget, while Terry/ARCHIE/each supporting agent get their own bucket."""
    if getattr(app, "_rate_mode", "bucket") == "legacy":
        _apply_rate_limit_legacy(app)
        return
    now = time.time()
    bkey = str(key) if key is not None else "_default"
    with app._rate_lock:
        bucket = app._profile_buckets.get(bkey)
        if bucket is None:
            bucket = _TokenBucket(app._max_per_hour, now)
            app._profile_buckets[bkey] = bucket
        retry_after = bucket.consume(now, 1.0)
    if retry_after is not None:
        raise RateLimitError(retry_after)
    # Human-like random delay between actions (per task, OUTSIDE the lock)
    delay = random.uniform(app._min_delay_s, app._max_delay_s)
    if delay > 0:
        time.sleep(delay)


# Per-task hard deadline — kept below the platform's ~180s client poll so a wedged task
# surfaces as a clean, bounded watchdog_timeout (and frees the profile lock) BEFORE the
# client gives up. On deadline the watchdog SIGKILLs the agent's wedged chrome, which
# unblocks the hung Playwright call so the skill thread unwinds + releases the lock. (#4372)
_TASK_DEADLINE_S = float(os.getenv("BROWSER_TASK_DEADLINE_S", "150"))


def _execute_task(app, task_id, agent_id, skill_name, params, idempotency_key=None, post_metadata=None):
    with app._tasks_lock:
        app._tasks[task_id]["status"] = "running"

    # Rate limiting — per-profile token bucket. On exhaustion, surface a NON-BLOCKING
    # rate_limited status (the platform reschedules) instead of sleeping under a lock.
    if not app.config.get("TESTING"):
        try:
            _apply_rate_limit(app, agent_id)
        except RateLimitError as rle:
            logger.info(
                "[RateLimit] agent %s rate_limited (retry ~%.0fs) — task %s deferred",
                agent_id, rle.retry_after_s, task_id,
            )
            with app._tasks_lock:
                app._tasks[task_id].update(
                    {
                        "status": "rate_limited",
                        "error": str(rle),
                        "retry_after": round(rle.retry_after_s, 1),
                    }
                )
            _log_task_to_db(
                task_id, agent_id, skill_name, params, "rate_limited", None, str(rle), 0,
                idempotency_key=idempotency_key, post_metadata=post_metadata,
            )
            return

    # Watchdog: if the skill exceeds the deadline, force-kill the agent's wedged chrome
    # so the per-profile lock frees and the hung Playwright call raises (the thread then
    # unwinds into the except below). Best-effort; cancelled on normal completion.
    _wd = {"fired": False}

    def _on_deadline():
        _wd["fired"] = True
        try:
            import skill_runner
            killed = skill_runner.kill_agent_chrome(agent_id)
            logger.error(
                "[Watchdog] task %s (%s / agent %s) exceeded %.0fs — force-killed %d "
                "chrome proc(s) to free the profile lock",
                task_id, skill_name, agent_id, _TASK_DEADLINE_S, killed,
            )
        except Exception as exc:
            logger.error("[Watchdog] task %s unwedge failed: %s", task_id, exc)

    timer = None
    if not app.config.get("TESTING"):
        timer = threading.Timer(_TASK_DEADLINE_S, _on_deadline)
        timer.daemon = True
        timer.start()

    start = datetime.now(timezone.utc)
    try:
        import skill_runner
        result = skill_runner.run(agent_id, skill_name, params)
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        with app._tasks_lock:
            app._tasks[task_id].update(
                {"status": "completed", "result": result, "duration_ms": duration_ms}
            )
        _log_task_to_db(
            task_id, agent_id, skill_name, params, "completed", result, None, duration_ms,
            idempotency_key=idempotency_key, post_metadata=post_metadata,
        )
    except Exception as exc:
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        err = str(exc)
        if _wd["fired"]:
            err = f"watchdog_timeout after {_TASK_DEADLINE_S:.0f}s (chrome force-killed to free lock): {err}"
        logger.error("task %s failed: %s", task_id, err)
        with app._tasks_lock:
            app._tasks[task_id].update(
                {"status": "failed", "error": err, "duration_ms": duration_ms}
            )
        _log_task_to_db(
            task_id, agent_id, skill_name, params, "failed", None, err, duration_ms,
            idempotency_key=idempotency_key, post_metadata=post_metadata,
        )
    finally:
        if timer is not None:
            timer.cancel()


def _log_task_to_db(
    task_id, agent_id, skill_name, params, status, result, error, duration_ms,
    idempotency_key=None, post_metadata=None,
):
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
                     triggered_by, task_id, idempotency_key, post_metadata, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                    task_id,
                    idempotency_key,
                    psycopg2.extras.Json(post_metadata) if post_metadata else None,
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
