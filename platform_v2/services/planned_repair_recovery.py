"""Explicit recovery for provably unclaimed work; never infer a dead worker."""

from uuid import uuid4
from psycopg2.extras import Json

from database import get_db_cursor
from services.repair_submission import metadata


def recovery_options(proposal, task):
    meta = metadata(proposal.get("metadata"))
    link = meta.get("planned_repair") or {}
    task_meta = metadata((task or {}).get("metadata"))
    args = metadata((task or {}).get("delegation_args"))
    associated = (
        meta.get("source") == "code_health_audit"
        and proposal.get("status") == "approved"
        and task
        and args.get("capability") == "codex_task"
        and metadata(args.get("args")).get("repair_proposal_id") == proposal.get("id")
        and not any(meta.get(key) for key in ("pr_number", "merged_pr", "repair_submission", "repair_artifacts"))
        and not task_meta.get("codex_pr")
        and not task_meta.get("codex_branch")
    )
    marker = task_meta.get("planned_cancellation") or {}
    cancelled_here = (
        marker.get("token")
        and marker.get("token") == link.get("cancellation_token")
        and marker.get("proposal_id") == proposal.get("id")
        and marker.get("task_id") == link.get("task_id")
    )
    return {
        "can_cancel": bool(associated and task.get("status") == "deferred"),
        "can_retry": bool(associated and task.get("status") == "cancelled" and cancelled_here),
    }


def recover_planned_work(proposal_id, requested_by, action, expected_task_id):
    """Compare attempt identity and lock both rows against the atomic host claim."""
    from services.audit_pipeline import creed_gate_pre_dispatch
    from services.delegation_service import delegate_task
    from services.planned_repair_service import CONTROL_KEY, _prompt, classify
    from services.time_utils import now_utc
    from services.work_control_service import is_enabled

    if action not in {"cancel", "retry"} or type(expected_task_id) is not int or expected_task_id <= 0:
        return {"success": False, "error": "A valid current coding task is required"}
    if action == "retry":
        gate = creed_gate_pre_dispatch(proposal_id)
        if not gate.get("approved"):
            return {"success": False, "error": gate.get("reason", "Governance refused retry")}
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT * FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        meta = metadata((row or {}).get("metadata"))
        link = meta.get("planned_repair") or {}
        if not row or link.get("task_id") != expected_task_id:
            return {"success": False, "error": "Coding attempt changed; refresh the proposal"}
        cur.execute("SELECT * FROM unified_tasks WHERE id=%s FOR UPDATE", (expected_task_id,))
        task = cur.fetchone()
        options = recovery_options(row, task)
        if not options["can_" + action]:
            return {
                "success": False,
                "error": "Only unclaimed queued work can be cancelled, and only that cancelled work can be retried. "
                "Blocked or running workers require operator investigation; no replacement was started.",
            }
        now = now_utc().isoformat()
        if action == "cancel":
            token = str(uuid4())
            marker = {
                "token": token,
                "proposal_id": proposal_id,
                "task_id": expected_task_id,
                "at": now,
                "by": str(requested_by),
            }
            cur.execute(
                "UPDATE unified_tasks SET status='cancelled',updated_at=NOW(),metadata=COALESCE(metadata,'{}'::jsonb) || %s WHERE id=%s AND status='deferred'",
                (Json({"planned_cancellation": marker}), expected_task_id),
            )
            stamp = dict(
                link,
                cancellation_token=token,
                cancelled_at=now,
                cancelled_by=str(requested_by),
                result_error="Queued work cancelled before the worker claimed it",
            )
            updates = {"planned_repair": stamp}
            result = {"success": True, "cancelled": True, "task_id": expected_task_id}
        else:
            route = classify(row)
            if not route.get("eligible"):
                return {"success": False, "error": route["reason"]}
            if not is_enabled(CONTROL_KEY, default=False):
                return {"success": False, "error": "Planned repair dispatch is disabled"}
            history = meta.get("planned_repair_attempts") or []
            if not isinstance(history, list) or len(history) >= 32:
                return {"success": False, "error": "Attempt history needs operator review"}
            task = delegate_task(
                capability="codex_task",
                reason=_prompt(proposal_id, route, meta),
                args={
                    "repair_proposal_id": proposal_id,
                    "repair_kind": route["kind"],
                    "file_path": route["file_path"],
                    "previous_task_id": expected_task_id,
                },
                delegation_source="automation",
                requested_by=str(requested_by),
                priority=7,
                cursor=cur,
            )
            if not task.get("success") or not task.get("task_id"):
                raise RuntimeError(task.get("error", "Replacement task was not created"))
            stamp = {
                "task_id": task["task_id"],
                "kind": route["kind"],
                "requested_at": now,
                "requested_by": str(requested_by),
                "previous_task_id": expected_task_id,
            }
            updates = {
                "planned_repair": stamp,
                "planned_repair_attempts": history
                + [dict(link, status="cancelled", replaced_at=now, replaced_by=str(requested_by))],
            }
            result = {
                "success": True,
                "queued": True,
                "task_id": task["task_id"],
                "message": "Cancelled work replaced; the finding remains open until verified.",
            }
        cur.execute(
            "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s WHERE id=%s",
            (Json(updates), proposal_id),
        )
    return result
