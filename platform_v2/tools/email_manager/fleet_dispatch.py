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
    # DELEGATES to the dispatcher (#6023). The polling logic lived here AND in
    # services/cluster_dispatch.py — two near-identical copies of a workaround for one
    # dispatcher-level gap, which is why KB #276153 kept recurring. The signature is
    # unchanged, so this module's callers are unaffected.
    from tools.department_hq.services.department_dispatcher import dispatch_awaiting_queue

    return dispatch_awaiting_queue(
        capability,
        prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        module_id=module_id,
        local_only=local_only,
        poll_timeout_s=poll_timeout_s,
    )
