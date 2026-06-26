"""Concrete resume handlers for interrupted bridge_jobs (#4499, slice-2 Scope A).

Registered against `job_recovery_service.RESUME_HANDLERS` at import. A handler
resumes the REAL remaining work for an interrupted job of its job_type.

The consciousness backlog families (batch_embedding / batch_analysis /
translate_batch) are run by an immediately-spawned daemon thread, not a generic
poller, and are idempotent: re-running re-selects only the rows that still need
work (WHERE embedding IS NULL / ai_analysis IS NULL / missing translation keys).
So resume == re-trigger the loop op via `_trigger_loop_op(op)`, which is
non-blocking (spawns a daemon thread), no-ops on an empty backlog, and dedups a
job already running. Honest: any failure returns executed=False (never faked).
"""

import logging

from services.job_recovery_service import register_resume_handler

logger = logging.getLogger(__name__)

# bridge_jobs.job_type -> consciousness server-loop op key
_CONSCIOUSNESS_OP_MAP = {
    "batch_analysis": "analysis",
    "batch_embedding": "embedding",
    "translate_batch": "translate",
}


def _resume_consciousness_backlog(cur, job_row: dict) -> dict:
    """Resume an interrupted consciousness backlog by re-kicking its loop op.

    `_trigger_loop_op` opens its own DB connection (no Flask context needed),
    re-selects only unprocessed items, and starts the next batch on a daemon
    thread — so this returns immediately and processes only remaining work.
    """
    op = _CONSCIOUSNESS_OP_MAP.get(job_row.get("job_type"))
    if not op:
        return {"executed": False, "detail": f"unknown consciousness job_type {job_row.get('job_type')!r}"}
    try:
        from tools.consciousness.processing_routes import _trigger_loop_op

        _trigger_loop_op(op)
        return {"executed": True, "detail": f"re-triggered consciousness '{op}' backlog"}
    except Exception as exc:
        logger.exception("consciousness backlog resume failed for job %s", job_row.get("id"))
        return {"executed": False, "detail": f"resume failed: {exc}"}


for _jt in _CONSCIOUSNESS_OP_MAP:
    register_resume_handler(_jt, _resume_consciousness_backlog)
