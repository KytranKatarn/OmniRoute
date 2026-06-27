"""Mail HQ — queue-aware DHQ dispatch helper for background/scheduler callers.

The mistake this fixes: `dispatch_json()` (→ `request_json`) is synchronous and
returns failure when the target agent is busy or the model is cold. The DHQ
dispatcher actually DEFERS cold-model work to `dispatch_pending_queue` and returns
`DispatchResult(success=False, queued=True, queue_id=N)`; the `model_dispatch_worker`
(15s) then routes that row to whichever fleet node has the model warm and writes
`result_response`. Treating `queued=True` as a hard failure (what email triage + the
draft job did) means the work is dropped instead of draining when an agent frees up.

This helper mirrors the proven pattern in
`media_studio/services/portrait_service._fleet_dispatch`: run inline when warm,
otherwise POLL the queue for the worker's result. It blocks (polls every 3s), so it
is for BACKGROUND callers only (the APScheduler email-sync + draft jobs) — never the
web thread (module-work-pattern.md).
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 3


def queued_dispatch_text(
    capability: str,
    prompt: str,
    *,
    system_prompt: str | None = None,
    json_mode: bool = False,
    module_id: str = "email_manager",
    local_only: bool = True,
    poll_timeout_s: int = 240,
) -> str | None:
    """Dispatch one LLM step through DHQ, queue-aware. Returns the response text, or None.

    - Runs inline + returns immediately when the model is warm on any node.
    - When the dispatcher queues the work (cold model / busy agent), polls
      `dispatch_pending_queue` until the model_dispatch_worker writes the result.
    - Returns None on hard failure, queued-task failure/expiry, or poll timeout —
      the caller decides the fallback (e.g. skip this item, retry next cycle).
    """
    # Lazy imports (mirrors triage_service) so module import stays light and the
    # ai_bridge/db sys.path is established by the app before first call.
    from database import get_db_cursor
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    dispatcher = get_dispatcher()
    result = dispatcher.request_work(
        capability=capability,
        prompt=prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        module_id=module_id,
        local_only=local_only,
        user_id=None,
    )

    if getattr(result, "success", False):
        return (getattr(result, "response", "") or "").strip()

    if not getattr(result, "queued", False):
        logger.warning("[mailhq-dispatch] hard failure cap=%s: %s", capability, getattr(result, "error", None))
        return None

    # Queued to the fleet cold-load queue — resolve the queue id and poll.
    qid = getattr(result, "queue_id", None)
    if not qid:
        m = re.search(r"id=(\d+)", getattr(result, "error", "") or "")
        qid = int(m.group(1)) if m else None
    if not qid:
        logger.warning(
            "[mailhq-dispatch] queued without a queue id cap=%s: %s", capability, getattr(result, "error", None)
        )
        return None

    logger.info("[mailhq-dispatch] cap=%s queued as #%s — polling for worker result", capability, qid)
    deadline = time.time() + poll_timeout_s
    while time.time() < deadline:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, result_response, error FROM dispatch_pending_queue WHERE id = %s",
                (qid,),
            )
            row = cur.fetchone()
        if not row:
            logger.warning("[mailhq-dispatch] queue row #%s disappeared (cap=%s)", qid, capability)
            return None
        status = row["status"] if isinstance(row, dict) else row[0]
        if status == "done":
            resp = row["result_response"] if isinstance(row, dict) else row[1]
            return (resp or "").strip()
        if status in ("failed", "expired"):
            err = row["error"] if isinstance(row, dict) else row[2]
            logger.warning("[mailhq-dispatch] queued task #%s %s cap=%s: %s", qid, status, capability, err)
            return None
        time.sleep(_POLL_INTERVAL_S)

    logger.warning("[mailhq-dispatch] poll timeout (%ss) qid=%s cap=%s", poll_timeout_s, qid, capability)
    return None
