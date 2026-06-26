"""Interrupted-job recovery for bridge_jobs (#1716 durable execution, slice 1).

State already persists (bridge_jobs.{total,completed,failed}_steps); the gap this
fills is RESUME/REPLAY. On restart or when a worker dies, a 'running' job is
abandoned — previously force-failed ("Cleared on restart"). Here we instead mark it
'interrupted' with a checkpoint and make it replayable.

Functions take a DB cursor so they are unit-testable with a stub cursor.
"""

import json
import logging

logger = logging.getLogger(__name__)

INTERRUPTED = "interrupted"


def _as_dict(row, cur, cols=None):
    """Normalize a fetched row to a plain dict for either cursor type.

    The DHQ endpoints use a RealDictCursor (rows are already dict-like); the unit
    tests use a tuple cursor (rows are tuples). Slice-1 assumed tuples only, which
    silently mis-mapped rows under the real RealDictCursor. Pass ``cols`` for a
    fixed-shape SELECT so tuple rows map positionally without needing
    ``cur.description``.
    """
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if cols is None:
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


# job_types whose execution is idempotent / re-entrant — safe to auto-re-dispatch on
# replay (single-item inference capabilities; re-running just produces a fresh result).
# Anything NOT in this set is cloned to 'pending' + flagged 'replay_needs_handler' and
# is NEVER auto-executed (batch/*_backlog jobs could double-process; unknown = unsafe).
RE_ENTRANT_JOB_TYPES = {
    "fact_check",
    "factcheck_quick",
    "geo_extraction",
    "bias_quick",
    "bias_analysis",
    "translate",
    "classify",
}

# --- #4499: per-job-type resume handlers (true mid-step resume, Scope A) ---
# A registered handler resumes the REAL remaining work for an interrupted job of
# its job_type (e.g. an idempotent consciousness backlog re-selects only the rows
# it hasn't processed yet). Registering a handler means replay resumes IN PLACE
# instead of cloning a 'pending' row (which nothing would pick up — there is no
# generic bridge_jobs poller). A handler is `fn(cur, job_row: dict) -> dict` and
# MUST be honest: return {"executed": False, ...} rather than fake success.
RESUME_HANDLERS = {}
_handlers_loaded = False


def register_resume_handler(job_type: str, fn) -> None:
    """Register a resume handler for a bridge_jobs job_type."""
    RESUME_HANDLERS[job_type] = fn


def _ensure_handlers_loaded() -> None:
    """Lazily import the concrete handlers module once so it self-registers.

    Kept lazy + guarded so handler registration does not depend on app-boot
    import order, and a broken/uninstalled handlers module can never break
    replay (we simply fall back to the slice-1 clone path).
    """
    global _handlers_loaded
    if _handlers_loaded:
        return
    _handlers_loaded = True
    try:
        import services.job_resume_handlers  # noqa: F401  (registers on import)
    except Exception:
        logger.exception("job_resume_handlers import failed — resume handlers disabled")


def _get_resume_handler(job_type: str):
    _ensure_handlers_loaded()
    return RESUME_HANDLERS.get(job_type)


def mark_interrupted_on_restart(cur) -> int:
    """Mark all currently-'running' jobs 'interrupted' with a checkpoint.

    Called once on app startup, replacing the blanket force-fail. Returns rowcount.
    """
    cur.execute(
        """
        UPDATE bridge_jobs
           SET status = %s,
               checkpoint = jsonb_build_object(
                   'completed_steps', completed_steps,
                   'total_steps', total_steps,
                   'reason', 'restart'),
               updated_at = NOW()
         WHERE status = 'running'
        """,
        (INTERRUPTED,),
    )
    return cur.rowcount


def reap_stale_running(cur, max_age_min: int = 20) -> int:
    """Mark 'running' jobs whose updated_at is older than max_age_min 'interrupted'.

    Catches jobs orphaned without a full restart. Returns rowcount.
    """
    cur.execute(
        """
        UPDATE bridge_jobs
           SET status = %s,
               checkpoint = jsonb_build_object(
                   'completed_steps', completed_steps,
                   'total_steps', total_steps,
                   'reason', 'stale'),
               updated_at = NOW()
         WHERE status = 'running'
           AND updated_at < NOW() - (%s || ' minutes')::interval
        """,
        (INTERRUPTED, str(max_age_min)),
    )
    return cur.rowcount


def list_interrupted(cur, limit: int = 50) -> list:
    """Return interrupted jobs (most recent first)."""
    cur.execute(
        """
        SELECT id, job_type, module_source, description, checkpoint,
               replay_of, replayed_at, created_at, updated_at
          FROM bridge_jobs
         WHERE status = %s
         ORDER BY updated_at DESC
         LIMIT %s
        """,
        (INTERRUPTED, limit),
    )
    return [_as_dict(row, cur) for row in cur.fetchall()]


def replay_job(cur, job_id: int) -> dict:
    """Clone an interrupted/failed job into a new 'pending' bridge_job.

    If the job_type is re-entrant, re-dispatch it via the DHQ dispatcher; otherwise
    leave the clone 'pending' and flag metadata.replay_needs_handler (no fake re-run).
    Returns {"new_job_id", "executed", "needs_handler"}.
    """
    cur.execute(
        "SELECT job_type, module_source, description, metadata, checkpoint, agent_name "
        "FROM bridge_jobs WHERE id = %s",
        (job_id,),
    )
    d = _as_dict(
        cur.fetchone(),
        cur,
        cols=["job_type", "module_source", "description", "metadata", "checkpoint", "agent_name"],
    )
    if not d:
        raise ValueError(f"bridge_job {job_id} not found")
    job_type = d["job_type"]
    module_source = d["module_source"]
    description = d["description"]
    metadata = d["metadata"]
    checkpoint = d["checkpoint"]
    agent_name = d["agent_name"]

    # #4499: if a resume handler is registered for this job_type, resume the real
    # remaining work IN PLACE (no useless 'pending' clone — nothing polls it).
    handler = _get_resume_handler(job_type)
    if handler is not None:
        result = handler(
            cur,
            {
                "id": job_id,
                "job_type": job_type,
                "module_source": module_source,
                "description": description,
                "metadata": metadata,
                "checkpoint": checkpoint,
                "agent_name": agent_name,
            },
        )
        cur.execute("UPDATE bridge_jobs SET replayed_at = NOW() WHERE id = %s", (job_id,))
        return {
            "new_job_id": result.get("new_job_id"),
            "executed": bool(result.get("executed", False)),
            "needs_handler": False,
            "resumed": True,
            "detail": result.get("detail"),
        }

    re_entrant = job_type in RE_ENTRANT_JOB_TYPES
    meta = dict(metadata or {})
    meta["replay_of"] = job_id
    if not re_entrant:
        meta["replay_needs_handler"] = True

    cur.execute(
        """
        INSERT INTO bridge_jobs
            (job_type, module_source, description, status, agent_name,
             metadata, checkpoint, replay_of, created_at, updated_at)
        VALUES (%s, %s, %s, 'pending', %s, %s::jsonb, %s::jsonb, %s, NOW(), NOW())
        RETURNING id
        """,
        (
            job_type,
            module_source,
            description,
            agent_name,
            json.dumps(meta),
            json.dumps(checkpoint) if checkpoint is not None else None,
            job_id,
        ),
    )
    ret = cur.fetchone()
    new_id = ret["id"] if isinstance(ret, dict) else ret[0]
    cur.execute("UPDATE bridge_jobs SET replayed_at = NOW() WHERE id = %s", (job_id,))

    executed = _dispatch_replay(job_type, description, new_id) if re_entrant else False
    return {"new_job_id": new_id, "executed": executed, "needs_handler": not re_entrant}


def _dispatch_replay(job_type: str, description, new_job_id: int) -> bool:
    """Re-dispatch a re-entrant job via the DHQ dispatcher. Returns True on dispatch."""
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        dispatch(
            capability=job_type,
            prompt=description or "",
            job_id=new_job_id,
        )
        return True
    except Exception:
        logger.exception("replay dispatch failed for bridge_job %s", new_job_id)
        return False
