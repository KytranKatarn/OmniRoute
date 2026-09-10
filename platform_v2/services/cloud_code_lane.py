"""Cloud coding lane (#6653 Phase 3a) — pure helpers, no DB, no Flask.

An explicit, ask-first path that sends ONE coding task to a cloud contractor
(OmniRoute) WITHOUT changing escalation_mode (it stays local_only — this is not
auto-escalation). Mirrors the A/B Cloud Comparison lane (#4661): the job is a
bridge_jobs row, the approval is an autonomy_approval_queue row linked by
metadata.approval_id, and a 30 s worker (agent_loop.cloud_code_worker) drains
approved jobs. Everything decision-shaped lives here so it is testable without
a database; the three adapters at the bottom are the ONLY places that touch
other subsystems, and tests monkeypatch them.

The cockpit button for this lane is Phase 4; app.py exposes the backend path.
"""

from __future__ import annotations

from typing import Optional

JOB_TYPE = "cloud_code"
MODULE_ID = "cloud_code_lane"
CAPABILITY = "code"  # on the cloud allowlist; never company data
ACTION_TYPE = "cloud_code_dispatch"  # Tier-2 approval type (Ship tab)
EXPIRE_SECONDS = 24 * 3600  # same horizon as the A/B lane


def build_job_metadata(
    *, prompt: str, system_prompt: Optional[str], provider_key: str, model: str, requested_by: str
) -> dict:
    return {
        "lane": MODULE_ID,
        "provider": provider_key,
        "model": model,
        "capability": CAPABILITY,
        "prompt": prompt,
        "system_prompt": system_prompt or "",
        "requested_by": requested_by,
    }


def plan_worker_action(job_status: str, approval_status: Optional[str], age_seconds: float) -> str:
    """'run' | 'cancel' | 'skip' for one job, from its linked approval's state."""
    if job_status != "pending":
        return "skip"
    st = (approval_status or "pending").strip().lower()
    # 'executed' is what the approval-queue drain writes once its executor branch
    # acknowledges an ask-first row (see agent_loop._execute_approved_action) — it
    # means the human said YES, not that this worker's job already ran.
    if st in ("approved", "executed"):
        return "run"
    if st in ("rejected", "denied", "timeout", "expired", "cancelled", "failed"):
        return "cancel"
    if age_seconds > EXPIRE_SECONDS:
        return "cancel"
    return "skip"


def summarize_result(res) -> dict:
    """Shape a DispatchResult into the JSON-safe record stored on the job."""
    meta = getattr(res, "metadata", None) or {}
    return {
        "success": bool(getattr(res, "success", False)),
        "response": getattr(res, "response", "") or "",
        "model_used": getattr(res, "model_used", "") or "",
        "provider": getattr(res, "provider", "") or "",
        "prompt_tokens": int(getattr(res, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(res, "completion_tokens", 0) or 0),
        "error": getattr(res, "error", None),
        # A cloud coding call MUST carry provenance; absence is flagged, not assumed.
        "served_model_resolved": bool(meta.get("served_model_resolved", False)),
        "routing_decision": meta.get("routing_decision"),
    }


# --- adapters (the only subsystem touchpoints; monkeypatched in tests) -----------


def code_allowed() -> bool:
    """The sovereignty boundary: may 'code' leave the cluster? Fails closed."""
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    return bool(get_dispatcher()._cloud_capability_allowed(CAPABILITY))


def active_provider(provider_key: str) -> Optional[dict]:
    from ai_bridge.external_providers import _get_provider_config

    cfg = _get_provider_config(provider_key)
    return cfg if cfg and cfg.get("is_active") else None


def request_tier2_approval(
    *, job_id: int, provider_key: str, model: str, prompt: str, requested_by: str
) -> Optional[int]:
    """Ask-first. Returns the approval id, or None when request_approval() could not
    enqueue (its per-action_type dedup: one pending cloud_code approval at a time)."""
    from ai_bridge.agent_loop import request_approval

    return request_approval(
        action_type=ACTION_TYPE,
        action_data={
            "job_id": job_id,
            "provider": provider_key,
            "model": model,
            "prompt_preview": prompt[:200],
            "requested_by": requested_by,
        },
        reason=f"Cloud coding task via {provider_key}:{model}",
        requested_by="cloud_code_lane",
        tier=2,
    )
