"""Cluster-wide, queue-aware DHQ dispatch helper for background/scheduler callers.

Why this exists (KB mistake #276153): `dispatch_json()` / `request_json()` is
synchronous and reports failure when the target agent is busy or the model is
cold. But the DHQ dispatcher actually DEFERS cold-model work to
`dispatch_pending_queue` and returns `DispatchResult(success=False,
queued=True, queue_id=N)`; the `model_dispatch_worker` then routes that row to
whichever node has the model warm and writes `result_response`. Treating
`queued=True` as a hard failure DROPS the work instead of letting it drain when
a node frees up.

This helper runs inline when a model is warm on ANY node, otherwise POLLS the
queue for the worker's result — so background work uses the FULL cluster and
waits for a cold-load instead of timing out. It blocks (polls every few
seconds), so it is for BACKGROUND callers only (APScheduler jobs) — never the
web thread (module-work-pattern.md, ADR-013).

This is the module-agnostic version of the proven pattern in
`email_manager/fleet_dispatch.queued_dispatch_text`. New background callers
should import from here.

Import:
    from services.cluster_dispatch import queued_dispatch_text
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 3


def _ensure_import_paths() -> None:
    """The dispatcher chain does `from db import ...` (resolved from the ai_bridge
    package dir). Add /app + the ai_bridge dir to sys.path so the dispatcher import
    works outside the app boot path (scheduler sidecar, bare exec). KB #272154.
    """
    import importlib.util
    import sys

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    spec = importlib.util.find_spec("ai_bridge")
    if spec and spec.submodule_search_locations:
        pkg_dir = list(spec.submodule_search_locations)[0]
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)


def queued_dispatch_text(
    capability: str,
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    module_id: str = "cluster_dispatch",
    local_only: bool = True,
    poll_timeout_s: int = 240,
    model_override: Optional[str] = None,
    job_id: Optional[int] = None,
    prefer_agent: Optional[str] = None,
) -> Optional[str]:
    """Dispatch one LLM step through DHQ, queue-aware. Returns response text, or None.

    - Runs inline + returns immediately when the model is warm on any node.
    - When the dispatcher queues the work (cold model / busy agent), polls
      `dispatch_pending_queue` until the model_dispatch_worker writes the result.
    - Returns None on hard failure, queued-task failure/expiry, or poll timeout —
      the caller decides the fallback (e.g. retry next cycle).

    Routes across the FULL cluster (hub + fleet nodes) via capability-based
    selection. `local_only=True` keeps cloud escalation off (background work).

    `job_id` links the execution to an existing `bridge_jobs` row so a multi-step
    caller keeps its progress/observability (batch_translate drives the Languages
    tab progress bar off it). `prefer_agent` biases agent selection without
    forcing it. Both are optional and default to None, so every pre-existing
    caller behaves exactly as before (#5626).
    """
    # ⚠️ `_ensure_import_paths()` STAYS HERE and must run BEFORE the dispatcher import.
    # This module is the PATH-SAFE facade: the scheduler sidecar and bare execs cannot
    # import department_dispatcher cold — it does `from db import ...` (ai_bridge) at
    # module scope and raises ModuleNotFoundError (KB #272154). Measured while building
    # #6023: importing the dispatcher directly from a bare exec failed exactly that way.
    # Flattening this facade into the dispatcher would break every sidecar caller, and
    # only at job time.
    #
    # The polling logic itself now lives in the dispatcher (one copy, at the choke
    # point); this stays the safe front door. Signature unchanged.
    _ensure_import_paths()
    from tools.department_hq.services.department_dispatcher import dispatch_awaiting_queue

    return dispatch_awaiting_queue(
        capability,
        prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        module_id=module_id,
        local_only=local_only,
        poll_timeout_s=poll_timeout_s,
        model_override=model_override,
        job_id=job_id,
        prefer_agent=prefer_agent,
    )
