"""Per-node image sessions: keep SDXL warm across consecutive portrait jobs (#7400).

Before this, every fleet image job swapped the node's Ollama models out first and, in ``finally``, ran
``_vram_restore_after_comfyui`` -- which calls ComfyUI ``/free {unload_models: true}`` and so discards the SDXL
checkpoint. The NEXT job then cold-loaded SDXL (~7-8 min) against a 600s clock, so back-to-back portraits could
never run warm even with no LLM traffic at all.

A *session* is: swap Ollama out ONCE when the first job lands on a node, run any number of jobs, and restore only
when the image queue has drained and a short grace has elapsed. The worker calls ``restore_idle`` every tick.

State is per process. The media worker is a single scheduler-side job (``max_instances=1``), so one process owns
all sessions; if that process restarts, sessions are simply forgotten (Ollama reloads models lazily on dispatch).
All mutation of ``_sessions`` / ``_running`` is under ``_lock``; the swap (HTTP) runs outside it, and a second job that
races in during the swap simply opens/overwrites the same node entry, which is harmless (the swap is idempotent).

KNOWN LIMIT (addressed by the node GPU lease, a separate change): nothing yet stops the LLM dispatcher from loading a
model onto a node while its image session is open, which would evict SDXL for the next job. This module only removes
the self-inflicted per-job eviction; it does not arbitrate between image and LLM work.
"""

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# platform_settings keys (all optional, bounded, fail-safe to the default)
SETTING_GRACE_S = "media:image_session_grace_s"
SETTING_COLD_TIMEOUT_S = "media:cold_load_timeout_s"
SETTING_WARM_TIMEOUT_S = "media:warm_timeout_s"
SETTING_MAX_RETRIES = "media:max_retries"

DEFAULT_GRACE_S = 180
DEFAULT_COLD_TIMEOUT_S = 1200
DEFAULT_WARM_TIMEOUT_S = 600
DEFAULT_MAX_RETRIES = 3


def setting_int(key: str, default: int, low: int, high: int) -> int:
    """Bounded integer from platform_settings; any error or junk value yields ``default``."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return default
        val = row.get("value") if isinstance(row, dict) else row[0]
        return max(low, min(high, int(val)))
    except Exception:
        return default


def _dispatcher():
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    return get_dispatcher()


def _default_swap(node_id):
    return _dispatcher()._vram_swap_for_comfyui(node_id) or []


def _default_restore(unloaded, node_id):
    _dispatcher()._vram_restore_after_comfyui(unloaded, node_id)


class ImageSessions:
    """Tracks which fleet nodes currently have Ollama swapped out for ComfyUI."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        swap: Callable = _default_swap,
        restore: Callable = _default_restore,
        lease=None,
        holder: Optional[str] = None,
        hb_interval_s: float = 30.0,
        start_heartbeat: bool = True,
    ):
        self._clock = clock
        self._swap = swap
        self._restore = restore
        # Per-node GPU lease (#7401): held while a session is open so the LLM dispatcher (when enforcing)
        # stays off the node. lease is anything with acquire/heartbeat/release(node_name, holder).
        self._lease = lease
        self._holder = holder or f"media-worker:{os.getpid()}"
        self._hb_interval_s = hb_interval_s
        self._start_heartbeat = start_heartbeat
        self._hb_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._sessions: Dict[str, dict] = {}
        self._running: Set[int] = set()

    # -- GPU lease (best effort; never blocks generation) -----------------------------------
    def _lease_call(self, name: str, node_name: str):
        try:
            lease = self._lease
            if lease is None:
                from services import node_gpu_lease as lease  # lazy: keeps this module importable standalone
            getattr(lease, name)(node_name, self._holder)
        except Exception as exc:
            logger.warning("[MediaStudio] GPU lease %s failed for %s: %s", name, node_name, exc)

    def _ensure_heartbeat(self) -> None:
        if not self._start_heartbeat:
            return
        with self._lock:
            if self._hb_thread is not None and self._hb_thread.is_alive():
                return
            self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="image-session-lease", daemon=True)
            self._hb_thread.start()

    def _heartbeat_loop(self) -> None:
        # One job can poll for 600-1200s with no other call into this module, so the lease needs its own pulse.
        while True:
            time.sleep(self._hb_interval_s)
            with self._lock:
                nodes = list(self._sessions)
                if not nodes:
                    self._hb_thread = None
                    return
            for name in nodes:
                self._lease_call("heartbeat", name)

    # -- job lifecycle -------------------------------------------------------------------
    def begin(self, node_name: str, node_id, queue_id: Optional[int] = None) -> dict:
        """Start a job on node_name. cold is True only for the job that opens the session."""
        with self._lock:
            if queue_id is not None:
                self._running.add(queue_id)
            session = self._sessions.get(node_name)
            if session is not None:
                session["last_end"] = None
                session["jobs"] += 1
        if session is not None:
            self._lease_call("heartbeat", node_name)
            return {"cold": False}
        # Swap outside the lock: it makes HTTP calls to the node.
        try:
            unloaded = list(self._swap(node_id) or [])
        except Exception as exc:  # a failed swap must not block generation
            logger.warning("[MediaStudio] image session swap failed on %s: %s", node_name, exc)
            unloaded = []
        with self._lock:
            self._sessions[node_name] = {
                "node_id": node_id,
                "unloaded": unloaded,
                "opened": self._clock(),
                "last_end": None,
                "jobs": 1,
            }
        self._lease_call("acquire", node_name)
        self._ensure_heartbeat()
        if unloaded:
            logger.info("[MediaStudio] image session opened on %s (freed %d Ollama model(s))", node_name, len(unloaded))
        return {"cold": True}

    def end(self, node_name: Optional[str], queue_id: Optional[int] = None) -> None:
        """Finish a job. The session stays open (SDXL stays resident) until restore_idle closes it."""
        with self._lock:
            if queue_id is not None:
                self._running.discard(queue_id)
            session = self._sessions.get(node_name) if node_name else None
            if session is not None:
                session["last_end"] = self._clock()
        if session is not None:
            self._lease_call("heartbeat", node_name)

    # -- idle handling ---------------------------------------------------------------------
    def restore_idle(self, pending_total: int, grace_s: Optional[int] = None) -> List[str]:
        """Close sessions that are idle past the grace AND whose queue has drained. Returns closed node names."""
        if pending_total > 0:
            return []
        if grace_s is None:
            grace_s = setting_int(SETTING_GRACE_S, DEFAULT_GRACE_S, 0, 3600)
        due = []
        with self._lock:
            now = self._clock()
            for name, session in list(self._sessions.items()):
                last_end = session["last_end"]
                if last_end is not None and now - last_end >= grace_s:
                    due.append((name, self._sessions.pop(name)))
        closed = []
        for name, session in due:
            try:
                if session["unloaded"]:
                    self._restore(session["unloaded"], session["node_id"])
            except Exception as exc:
                logger.warning("[MediaStudio] image session restore failed on %s: %s", name, exc)
            # Release only after Ollama is restored, so LLM dispatch never races the reload.
            self._lease_call("release", name)
            closed.append(name)
            logger.info("[MediaStudio] image session closed on %s after %d job(s)", name, session["jobs"])
        return closed

    # -- introspection ---------------------------------------------------------------------
    def running_ids(self) -> Set[int]:
        with self._lock:
            return set(self._running)

    def open_nodes(self) -> List[str]:
        with self._lock:
            return list(self._sessions)


_SESSIONS = ImageSessions()


def get_sessions() -> ImageSessions:
    return _SESSIONS


def requeue_or_fail(queue_id: int, waited_s: int, get_cursor=None) -> str:
    """After a fleet timeout: put the row back to ``pending`` (counting the attempt) or fail it for good.

    Returns ``'requeued'`` or ``'failed'``. Replaces the old behaviour, where the timeout marked the row
    ``failed`` while its own message promised "will retry automatically" -- nothing ever retried it.
    """
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    max_retries = setting_int(SETTING_MAX_RETRIES, DEFAULT_MAX_RETRIES, 0, 20)
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute("SELECT params FROM media_generation_queue WHERE id = %s", (queue_id,))
        row = cur.fetchone()
        params = (row.get("params") if isinstance(row, dict) else (row[0] if row else None)) or {}
        attempts = int(params.get("retry_count") or 0)
        if attempts >= max_retries:
            cur.execute(
                "UPDATE media_generation_queue SET status = 'failed', completed_at = NOW(), error_message = %s "
                "WHERE id = %s",
                (
                    f"Timed out after {waited_s}s on {attempts + 1} attempt(s) - giving up (max retries reached)",
                    queue_id,
                ),
            )
            return "failed"
        cur.execute(
            "UPDATE media_generation_queue SET status = 'pending', started_at = NULL, "
            "params = params || jsonb_build_object('retry_count', %s::int), error_message = %s WHERE id = %s",
            (attempts + 1, f"Timed out after {waited_s}s (attempt {attempts + 1}) - requeued", queue_id),
        )
        return "requeued"


def reap_stuck(get_cursor=None, threshold_min: Optional[int] = None, running: Optional[Set[int]] = None) -> list:
    """Reset media rows stuck in ``generating``/``dispatched``; fail those that already exhausted their retries.

    Skips rows the worker is actively running (``running``), so a slow cold-loading job is not reaped from
    under its own polling loop.
    """
    if get_cursor is None:
        from database import get_db_cursor as get_cursor
    if threshold_min is None:
        cold = setting_int(SETTING_COLD_TIMEOUT_S, DEFAULT_COLD_TIMEOUT_S, 60, 7200)
        threshold_min = max(15, cold // 60 + 5)
    max_retries = setting_int(SETTING_MAX_RETRIES, DEFAULT_MAX_RETRIES, 0, 20)
    skip = sorted(running if running is not None else get_sessions().running_ids())
    with get_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
               SET status = CASE WHEN COALESCE((params->>'retry_count')::int, 0) >= %(max)s
                                 THEN 'failed' ELSE 'pending' END,
                   started_at = NULL,
                   completed_at = CASE WHEN COALESCE((params->>'retry_count')::int, 0) >= %(max)s
                                       THEN NOW() ELSE completed_at END,
                   error_message = CASE WHEN COALESCE((params->>'retry_count')::int, 0) >= %(max)s
                                        THEN 'Stuck too long - giving up (max retries reached)'
                                        ELSE error_message END,
                   params = params || jsonb_build_object('retry_count', COALESCE((params->>'retry_count')::int, 0) + 1)
             WHERE status IN ('generating', 'dispatched')
               AND started_at < NOW() - make_interval(mins => %(mins)s)
               AND NOT (id = ANY(%(skip)s::int[]))
            RETURNING id, media_type, status, params->>'model' AS model
            """,
            {"max": max_retries, "mins": threshold_min, "skip": skip},
        )
        return cur.fetchall() or []
