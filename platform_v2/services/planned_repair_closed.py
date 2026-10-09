"""Track closed planned PRs and record replacement intent; never execute it."""

import logging
import re
from uuid import uuid4
from psycopg2.extras import Json
from database import get_db_cursor
from services.planned_repair_results import REPO
from services.repair_submission import metadata


logger = logging.getLogger(__name__)


def _identity(proposal, task):
    meta = metadata(proposal.get("metadata"))
    link = meta.get("planned_repair") or {}
    args = metadata((task or {}).get("delegation_args"))
    task_meta = metadata((task or {}).get("metadata"))
    number = meta.get("pr_number")
    branch = task_meta.get("codex_branch") or ""
    if (
        meta.get("source") != "code_health_audit"
        or meta.get("apply_mode") != "planned_codex_pr"
        or type(link.get("task_id")) is not int
        or type(number) is not int
        or number <= 0
        or not task
        or task.get("id") != link.get("task_id")
        or task_meta.get("codex_pr") != number
        or args.get("capability") != "codex_task"
        or metadata(args.get("args")).get("repair_proposal_id") != proposal.get("id")
        or not isinstance(branch, str)
        or not re.fullmatch(r"codex/[a-z0-9-]+", branch)
    ):
        raise ValueError("Planned task and PR association is unavailable")
    return {"repo": REPO, "task_id": link["task_id"], "pr_number": number, "branch": branch}


def observe_pr(proposal, task, github):
    identity = _identity(proposal, task)
    ok, pr = github._api_get(f"/repos/{REPO}/pulls/{identity['pr_number']}")
    if not ok or not isinstance(pr, dict):
        raise ValueError("GitHub PR state is unavailable")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    sha = head.get("sha") or ""
    if (
        pr.get("number") != identity["pr_number"]
        or head.get("ref") != identity["branch"]
        or (head.get("repo") or {}).get("full_name") != REPO
        or (base.get("repo") or {}).get("full_name") != REPO
        or base.get("ref") != "main"
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or pr.get("state") not in {"open", "closed"}
        or type(pr.get("merged")) is not bool
        or (pr.get("merged") and pr.get("state") != "closed")
    ):
        raise ValueError("GitHub PR identity or state does not match planned work")
    state = "merged" if pr["merged"] else pr["state"]
    if state == "closed" and (not pr.get("closed_at") or pr.get("merged_at")):
        raise ValueError("Closed-unmerged PR evidence is incomplete")
    return dict(identity, version=1, state=state, head_sha=sha, closed_at=pr.get("closed_at"))


def replacement_progress(proposal, task):
    """All execution stays disabled, even if a future worker adds stop evidence."""
    meta = metadata(proposal.get("metadata"))
    observation = meta.get("planned_pr_observation") or {}
    intent = meta.get("planned_replacement_request") or {}
    result = {
        "execution_enabled": False,
        "can_request": False,
        "request": intent,
        "state": observation.get("state"),
        "head_sha": observation.get("head_sha"),
        "reason": "Verified worker-stop evidence and replacement execution are not available",
    }
    try:
        identity = _identity(proposal, task)
        matches = observation.get("version") == 1 and all(observation.get(k) == v for k, v in identity.items())
        result["can_request"] = bool(
            proposal.get("status") == "fix_requested"
            and matches
            and observation.get("state") == "closed"
            and not meta.get("merged_pr")
            and not meta.get("planned_pr_tracking_error")
            and intent.get("status") != "requested"
        )
    except ValueError as exc:
        result["reason"] = str(exc)
    if meta.get("planned_pr_tracking_error"):
        result["reason"] = meta["planned_pr_tracking_error"]
    elif intent.get("status") == "invalidated":
        result["reason"] = intent.get("invalidated_reason", "Prior request no longer matches the PR")
    return result


def request_replacement(proposal_id, requested_by, task_id, pr_number, head_sha):
    """Record admin intent atomically; no task creation, HTTP, inference or closure."""
    from services.audit_pipeline import creed_gate_pre_dispatch
    from services.planned_repair_service import classify
    from services.time_utils import now_utc

    if (
        type(task_id) is not int
        or task_id <= 0
        or type(pr_number) is not int
        or pr_number <= 0
        or not isinstance(head_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
    ):
        return {"success": False, "error": "Current task, PR and head identity are required"}
    gate = creed_gate_pre_dispatch(proposal_id)
    if not gate.get("approved"):
        return {"success": False, "error": gate.get("reason", "Governance refused replacement request")}
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT * FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Proposal not found"}
        meta = metadata(row.get("metadata"))
        observation = meta.get("planned_pr_observation") or {}
        if any(
            observation.get(k) != v
            for k, v in {"task_id": task_id, "pr_number": pr_number, "head_sha": head_sha}.items()
        ):
            return {"success": False, "error": "PR or coding attempt changed; refresh the proposal"}
        cur.execute("SELECT * FROM unified_tasks WHERE id=%s FOR SHARE", (task_id,))
        task = cur.fetchone()
        intent = meta.get("planned_replacement_request") or {}
        duplicate = intent.get("status") == "requested" and all(
            intent.get(k) == observation.get(k) for k in ("task_id", "pr_number", "head_sha")
        )
        # A duplicate must still refer to currently closed, associated work.
        candidate_meta = dict(meta, planned_replacement_request={})
        eligible = replacement_progress(dict(row, metadata=candidate_meta), task)["can_request"]
        if not eligible:
            return {"success": False, "error": "A tracked closed-unmerged planned PR is required"}
        candidate_meta.pop("pr_number", None)
        candidate_meta.pop("repair_submission", None)
        route = classify(dict(row, status="approved", metadata=candidate_meta))
        if not route.get("eligible"):
            return {"success": False, "error": route["reason"]}
        if duplicate:
            return {"success": True, "already_requested": True, "request_id": intent["id"], "execution_enabled": False}
        history = meta.get("planned_replacement_history") or []
        if not isinstance(history, list) or len(history) >= 32:
            return {"success": False, "error": "Replacement history needs operator review"}
        intent_new = {
            "id": str(uuid4()),
            "status": "requested",
            "task_id": task_id,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "requested_by": str(requested_by),
            "requested_at": now_utc().isoformat(),
        }
        cur.execute(
            "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s WHERE id=%s",
            (
                Json(
                    {
                        "planned_replacement_request": intent_new,
                        "planned_replacement_history": history + ([intent] if intent else []),
                    }
                ),
                proposal_id,
            ),
        )
    return {
        "success": True,
        "recorded": True,
        "request_id": intent_new["id"],
        "execution_enabled": False,
        "message": "Replacement request recorded. No coding starts until verified worker-stop evidence and replacement execution are available.",
    }


def reconcile_closed_planned(limit=3):
    from services.time_utils import now_utc
    from tools.repair_bay.services import github_service as github

    with get_db_cursor(commit=False) as (_, cur):
        cur.execute(
            """SELECT * FROM improvement_proposals WHERE status IN ('pr_open','fix_requested')
            AND metadata->>'source'='code_health_audit' AND metadata->>'apply_mode'='planned_codex_pr'
            AND NOT (metadata ? 'merged_pr')
            ORDER BY COALESCE(metadata->>'planned_pr_checked_at',''),id LIMIT %s""",
            (max(1, min(int(limit), 10)),),
        )
        rows = [dict(row) for row in cur.fetchall()]
    tracked = blocked = 0
    for row in rows:
        original = metadata(row["metadata"])
        task_id = (original.get("planned_repair") or {}).get("task_id")
        observation = None
        try:
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute("SELECT * FROM unified_tasks WHERE id=%s", (task_id,))
                task = cur.fetchone()
            # Fetch GitHub outside locks; revalidate the task snapshot under lock below.
            observation = observe_pr(row, task, github)
            error = None
        except Exception as exc:
            error = str(exc)[:300]
            blocked += 1
            logger.warning("Closed-PR tracking blocked proposal=%s task=%s: %s", row["id"], task_id, error)
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("SELECT * FROM improvement_proposals WHERE id=%s FOR UPDATE", (row["id"],))
            current = cur.fetchone()
            if not current or current["status"] != row["status"] or metadata(current.get("metadata")) != original:
                continue
            updates = {"planned_pr_checked_at": now_utc().isoformat(), "planned_pr_tracking_error": error}
            status = row["status"]
            if observation:
                cur.execute("SELECT * FROM unified_tasks WHERE id=%s FOR SHARE", (task_id,))
                locked = cur.fetchone()
                if (
                    not locked
                    or locked.get("id") != task.get("id")
                    or locked.get("metadata") != task.get("metadata")
                    or locked.get("delegation_args") != task.get("delegation_args")
                ):
                    # Do not leave the earlier observation actionable after a task race.
                    observation = None
                    updates["planned_pr_tracking_error"] = "Coding task changed during PR observation; awaiting recheck"
                    blocked += 1
                    logger.warning(
                        "Closed-PR task snapshot changed proposal=%s task=%s; recheck next run", row["id"], task_id
                    )
            if observation:
                updates["planned_pr_observation"] = observation
                status = "fix_requested" if observation["state"] == "closed" else "pr_open"
                intent = original.get("planned_replacement_request") or {}
                if intent.get("status") == "requested" and (
                    observation["state"] != "closed"
                    or any(intent.get(k) != observation.get(k) for k in ("task_id", "pr_number", "head_sha"))
                ):
                    updates["planned_replacement_request"] = dict(
                        intent,
                        status="invalidated",
                        invalidated_at=now_utc().isoformat(),
                        invalidated_reason="PR reopened, merged or changed; prior request cannot be executed",
                    )
                tracked += 1
            cur.execute(
                "UPDATE improvement_proposals SET status=%s,metadata=COALESCE(metadata,'{}'::jsonb) || %s WHERE id=%s",
                (status, Json(updates), row["id"]),
            )
    return {"checked": len(rows), "tracked": tracked, "blocked": blocked}
