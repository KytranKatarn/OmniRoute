"""
Loop Control Service — Server-side loop state management.

Extracted from consciousness/processing_routes.py to enable reuse
by Autonomy and other modules without importing consciousness internals.

The actual triggering of loop operations (which depends on consciousness-specific
job runners) is injected via `set_trigger_fn()` — processing_routes.py calls this
at import time to wire up _trigger_loop_op.
"""

import json
import logging
import os
from database import _get_db_password
import threading
from datetime import datetime, timezone

import psycopg2

logger = logging.getLogger("services.loop_service")

# ── Constants ─────────────────────────────────────────────────────
VALID_LOOP_OPS = ("analysis", "embedding", "translate")
_LOOP_CONFIG_KEY = "consciousness_server_loops"
_RETRY_CONFIG_KEY = "consciousness_loop_retries"
_BACKOFF_DELAYS = [30, 120, 600, 1800, 1800]
_loop_failures = {}  # { op: count } — reset on success, stop after 3

# ── Trigger function injection ────────────────────────────────────
# processing_routes.py sets this to its _trigger_loop_op at import time
_trigger_fn = None


def set_trigger_fn(fn):
    """Inject the trigger function (called by processing_routes.py at import)."""
    global _trigger_fn
    _trigger_fn = fn


def _call_trigger(op):
    """Call the injected trigger function, or warn if not set."""
    if _trigger_fn is None:
        logger.warning("[LoopService] No trigger function set — cannot trigger %s", op)
        return
    _trigger_fn(op)


# ── DB helper ─────────────────────────────────────────────────────
def get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ── Parse helper ──────────────────────────────────────────────────
def _parse_loops(raw):
    """Safely parse loop state from DB (may be dict or JSON string)."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Loop state read/write ─────────────────────────────────────────
def get_server_loops():
    """Read loop state from DB. Returns dict like {"analysis": true, ...}"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = %s", (_LOOP_CONFIG_KEY,))
        row = cur.fetchone()
        cur.close()
        return _parse_loops(row[0]) if row else {}
    except Exception:
        return {}
    finally:
        if conn:
            conn.close()


def set_server_loop(op, enabled):
    """Toggle a single loop op in the DB."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = %s", (_LOOP_CONFIG_KEY,))
        row = cur.fetchone()
        loops = _parse_loops(row[0]) if row else {}
        loops[op] = bool(enabled)
        cur.execute(
            """
            INSERT INTO system_config (key, value) VALUES (%s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = %s::jsonb
            """,
            (_LOOP_CONFIG_KEY, json.dumps(loops), json.dumps(loops)),
        )
        conn.commit()
        cur.close()
        if not enabled:
            _loop_failures.pop(op, None)
        return loops
    finally:
        if conn:
            conn.close()


# ── Retry state ───────────────────────────────────────────────────
def _get_retry_state():
    """Read retry state from DB. Returns dict like {"analysis": {"count": 2, ...}}"""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = %s", (_RETRY_CONFIG_KEY,))
        row = cur.fetchone()
        cur.close()
        return _parse_loops(row[0]) if row else {}
    except Exception:
        return {}
    finally:
        if conn:
            conn.close()


def _set_retry_state(state):
    """Persist retry state to system_config."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        payload = json.dumps(state)
        cur.execute(
            """
            INSERT INTO system_config (key, value) VALUES (%s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = %s::jsonb
            """,
            (_RETRY_CONFIG_KEY, payload, payload),
        )
        conn.commit()
        cur.close()
    finally:
        if conn:
            conn.close()


def _record_retry_failure(op, error_msg=""):
    """Increment retry count for an op and record failure timestamp."""
    state = _get_retry_state()
    op_state = state.get(op, {"count": 0})
    op_state["count"] = op_state.get("count", 0) + 1
    op_state["last_failure"] = datetime.now(timezone.utc).isoformat() + "Z"
    op_state["last_error"] = str(error_msg)[:200] if error_msg else ""
    state[op] = op_state
    _set_retry_state(state)
    return op_state["count"]


def _record_retry_success(op):
    """Reset retry count on success and record success timestamp."""
    state = _get_retry_state()
    op_state = state.get(op, {})
    op_state["count"] = 0
    op_state["last_success"] = datetime.now(timezone.utc).isoformat() + "Z"
    state[op] = op_state
    _set_retry_state(state)


def _get_backoff_delay(retry_count):
    """Return backoff delay in seconds for a given retry count (0-indexed)."""
    if retry_count <= 0:
        return 3  # No failures — normal cooldown
    idx = min(retry_count - 1, len(_BACKOFF_DELAYS) - 1)
    return _BACKOFF_DELAYS[idx]


# ── Retrigger logic ───────────────────────────────────────────────
def server_loop_retrigger(job_type, module_source, final_status):
    """Called by bridge_dispatcher.complete_job() to auto-retrigger the next batch.

    Uses exponential backoff on failure: 30s -> 2m -> 10m -> 30m (cap).
    Auto-disables after 5 consecutive failures.
    On success: resets retry count and delay to 0.
    """
    if module_source != "consciousness":
        return
    # Map job_type -> loop op key
    type_to_op = {
        "batch_analysis": "analysis",
        "batch_embedding": "embedding",
        "translate_batch": "translate",
    }
    op = type_to_op.get(job_type)
    if not op:
        return

    loops = get_server_loops()
    if not loops.get(op):
        return

    # Handle failure — exponential backoff
    if final_status != "completed":
        error_msg = f"Job {job_type} ended with status: {final_status}"
        retry_count = _record_retry_failure(op, error_msg)
        _loop_failures[op] = retry_count

        if retry_count >= 5:
            logger.error(
                f"[ServerLoop] ALERT: {op} failed {retry_count} consecutive times — resetting counter but keeping loop ENABLED. Investigate!"
            )
            _loop_failures.pop(op, None)
            return

        delay = _get_backoff_delay(retry_count)
        logger.warning(f"[ServerLoop] {op} failed (attempt {retry_count}/5) — " f"retrying in {delay}s (backoff)")

        def _backoff_trigger():
            import time

            time.sleep(delay)
            try:
                _call_trigger(op)
            except Exception as e:
                logger.error(f"[ServerLoop] Backoff retrigger {op} failed: {e}")

        t = threading.Thread(target=_backoff_trigger, daemon=True)
        t.start()
        return

    # Success — reset retry state and retrigger quickly
    _loop_failures.pop(op, None)
    _record_retry_success(op)

    def _delayed_trigger():
        import time

        time.sleep(3)  # Cooldown — must be faster than browser loop (2s + network)
        try:
            _call_trigger(op)
        except Exception as e:
            logger.error(f"[ServerLoop] Failed to retrigger {op}: {e}")

    t = threading.Thread(target=_delayed_trigger, daemon=True)
    t.start()
    logger.info(f"[ServerLoop] {op} completed — retriggering in 3s")


# ── Startup resume ────────────────────────────────────────────────
def startup_resume_loops():
    """Resume any enabled server loops that have no running jobs.

    Called once at app startup to recover from restarts mid-loop.
    """

    def _resume():
        import time

        time.sleep(15)  # Let platform fully boot + warmup
        try:
            # Reap zombie jobs from previous run — these threads died on restart
            conn0 = get_db()
            cur0 = conn0.cursor()
            cur0.execute(
                """
                UPDATE bridge_jobs
                SET status = 'failed', completed_at = NOW()
                WHERE status = 'running'
                AND module_source = 'consciousness'
                AND created_at < NOW() - INTERVAL '30 seconds'
                RETURNING id, job_type
                """
            )
            reaped = cur0.fetchall()
            conn0.commit()
            cur0.close()
            conn0.close()
            for rid, rtype in reaped:
                logger.info(f"[ServerLoop] Reaped zombie job #{rid} ({rtype})")

            loops = get_server_loops()
            if not any(loops.values()):
                return

            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT job_type FROM bridge_jobs WHERE status = 'running'")
            running_types = {r[0] for r in cur.fetchall()}
            cur.close()
            conn.close()

            op_to_job_type = {
                "analysis": "batch_analysis",
                "embedding": "batch_embedding",
                "translate": "translate_batch",
            }

            for op, enabled in loops.items():
                if not enabled:
                    continue
                jtype = op_to_job_type.get(op)
                if jtype and jtype not in running_types:
                    logger.info(f"[ServerLoop] Startup resume: kicking off {op}")
                    try:
                        _call_trigger(op)
                    except Exception as e:
                        logger.error(f"[ServerLoop] Startup resume {op} failed: {e}")
                    time.sleep(5)  # Stagger launches
        except Exception as e:
            logger.error(f"[ServerLoop] startup_resume_loops failed: {e}")

    t = threading.Thread(target=_resume, daemon=True)
    t.start()
