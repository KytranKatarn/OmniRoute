"""Archie-as-delegate — Claude → Archie task handoff (Project #276 Phase 1).

Surface for external callers (Claude via MCP, Kytran via Telegram/CLI)
to hand work to A.R.C.H.I.E. by capability tag. The task is persisted
into ``unified_tasks`` with ``delegation_source`` set; the agent-loop
worker (``_run_delegate_task_worker``) picks it up and routes to the
right executor.

Two execution paths:

1. **Known-tool shortcut** — capabilities that map to MCP/service
   functions we already ship (``run_qa_suite``, ``run_misroute_audit``,
   ``health_check``) invoke the target directly. Fast, deterministic.
2. **LLM dispatch** — everything else goes through
   ``department_dispatcher.dispatch(capability, prompt)`` so the DHQ
   dispatcher can pick an agent, route through Ollama/cloud, and apply
   C.R.E.E.D. governance.

Rule: NO cloud escalation bypasses the dispatcher. Kytran approval
gates and cost tracking apply exactly as they do for normal dispatch.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Capabilities that bypass the LLM dispatcher and invoke a deterministic
# service function directly. Extend as new "skills Archie can do" land.
KNOWN_TOOL_CAPABILITIES = {
    "run_qa_suite",
    "run_misroute_audit",
    "health_check",
    "check_platform_health",
    "check_dep_drift",
    "run_misroute_to_proposal_adapter",
    "deploy_static",
    "deploy_vps",
    "portrait_refinement",
    "translation_coverage_scan",
    "visual_scan",  # P.R.O.B.E. Playwright visual verification — logs and completes
    "document_pr",  # persist a coder-doc vault_note for a merged PR (deterministic store)
}

VALID_DELEGATION_SOURCES = {
    "claude",
    "user_cli",
    "telegram",
    "web_chat",
    "mcp_client",
    "automation",
}


def delegate_task(
    capability: str,
    reason: str,
    args: Optional[Dict[str, Any]] = None,
    delegation_source: str = "mcp_client",
    requested_by: str = "mcp_client",
    streaming_channel: Optional[str] = None,
    project_id: Optional[int] = None,
    priority: int = 5,
) -> Dict[str, Any]:
    """Persist a delegated task to ``unified_tasks`` for worker pickup.

    Returns ``{"success": True, "task_id": int, "title": str}`` on
    success, ``{"success": False, "error": str}`` on validation failure.
    """
    if not capability or not str(capability).strip():
        return {"success": False, "error": "capability is required"}
    if not reason or not str(reason).strip():
        return {"success": False, "error": "reason is required"}
    if delegation_source not in VALID_DELEGATION_SOURCES:
        return {
            "success": False,
            "error": (
                f"Invalid delegation_source {delegation_source!r}. " f"Valid: {sorted(VALID_DELEGATION_SOURCES)}"
            ),
        }
    if not 1 <= priority <= 10:
        return {"success": False, "error": "priority must be 1..10"}

    delegation_args = {
        "capability": capability,
        "args": args or {},
        "reason": reason,
        "requested_by": requested_by,
    }
    title = f"[DELEGATE:{delegation_source}] {capability}"[:500]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO unified_tasks
                (project_id, title, description, status, priority, task_type,
                 delegation_source, delegation_args, streaming_channel)
            VALUES (%s, %s, %s, 'pending', %s, 'implementation',
                    %s, %s::jsonb, %s)
            RETURNING id
            """,
            (
                project_id,
                title,
                f"Delegated by {requested_by} via {delegation_source}: {reason}",
                priority,
                delegation_source,
                json.dumps(delegation_args),
                streaming_channel,
            ),
        )
        task_id = cur.fetchone()["id"]

    logger.info(
        "Delegated task #%d: capability=%s source=%s requested_by=%s",
        task_id,
        capability,
        delegation_source,
        requested_by,
    )
    return {
        "success": True,
        "task_id": task_id,
        "title": title,
        "uses_known_tool": capability in KNOWN_TOOL_CAPABILITIES,
    }


def execute_delegated_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single delegated task row and return a result dict.

    Caller (the worker loop) is responsible for flipping task status
    and writing work_notes based on the returned dict. Keeping status
    mutations out of this function makes it easy to unit-test with
    mocks and also lets the worker loop own retry/timeout logic.

    Returns ``{"success": bool, "summary": str, "result": Any, "error": Optional[str]}``.
    """
    try:
        args = task.get("delegation_args") or {}
        if isinstance(args, str):
            args = json.loads(args)
        capability = args.get("capability")
        payload = args.get("args") or {}
        reason = args.get("reason", "")
        delegation_source = task.get("delegation_source") or args.get("delegation_source") or "mcp_client"

        if not capability:
            return {
                "success": False,
                "summary": "No capability in delegation_args",
                "error": "missing_capability",
            }

        # Auto-route PR documentation delegations (capability='documentation'
        # carrying a pr_number, e.g. from the merge-pr skill Step 8) to the
        # deterministic document_pr known-tool. The generic dispatcher path
        # never persisted to the KB, so PR docs were silently lost (#3519).
        if capability == "documentation" and (payload or {}).get("pr_number"):
            capability = "document_pr"

        if capability in KNOWN_TOOL_CAPABILITIES:
            # Dedup rapid-fire deploy requests: if a *newer* pending deploy
            # for the same domain exists, this task is superseded — skip it.
            if capability in ("deploy_static", "deploy_vps"):
                domain = payload.get("domain")
                task_id = task.get("id")
                if domain and task_id:
                    superseded = _is_deploy_superseded(task_id, capability, domain)
                    if superseded:
                        logger.info(
                            "deploy_dedup: task #%s (%s %s) superseded by newer pending task — skipping",
                            task_id,
                            capability,
                            domain,
                        )
                        return {
                            "success": True,
                            "summary": (f"{capability} {domain}: skipped — superseded by newer pending deploy"),
                            "result": {"domain": domain, "skipped": True, "reason": "superseded"},
                        }
            return _execute_known_tool(capability, payload, reason)

        return _execute_via_dispatcher(capability, payload, reason, origin=delegation_source)
    except Exception as exc:
        logger.exception("execute_delegated_task failed for task #%s", task.get("id"))
        return {
            "success": False,
            "summary": f"Executor raised: {type(exc).__name__}: {exc}",
            "error": str(exc),
        }


def _is_deploy_superseded(task_id: int, capability: str, domain: str) -> bool:
    """Return True if a newer pending deploy task for the same domain exists.

    Prevents duplicate Hostinger full-site deploys when B.A.S.E. queues
    several rapid-fire requests for the same domain (e.g. portrait batch
    approved → 3 tasks created in 30s). Only the newest pending task runs;
    older ones skip silently.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM unified_tasks
                WHERE id > %s
                  AND completed = FALSE
                  AND delegation_args->>'capability' = %s
                  AND delegation_args->'args'->>'domain' = %s
                """,
                (task_id, capability, domain),
            )
            row = cur.fetchone()
            return (row["cnt"] if isinstance(row, dict) else row[0]) > 0
    except Exception:
        logger.exception("_is_deploy_superseded query failed — not suppressing deploy")
        return False


def _document_pr(payload: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    """Deterministically persist a coder-doc vault_note for a merged PR.

    Replaces the old ``capability='documentation'`` dispatch path, which sent a
    prompt to C.O.D.E.X. but NEVER wrote to ``knowledge_base`` (#3519) — so PR
    docs were silently lost. This ALWAYS persists a structured vault_note built
    from PR metadata + the F.O.R.G.E. review summary already stored in the DB,
    independent of any LLM call (the LLM step was the unreliable part).
    """
    pr_number = payload.get("pr_number")
    if not pr_number:
        return {
            "success": False,
            "summary": "document_pr requires pr_number in args",
            "error": "missing_pr_number",
        }

    pr_title = payload.get("pr_title") or f"PR #{pr_number}"
    repo = payload.get("repo") or "KytranKatarn/archie-platform"

    # Best-effort: pull the diff-grounded F.O.R.G.E. review already in the DB.
    review: Dict[str, Any] = {}
    try:
        from tools.repair_bay.services.pr_review_service import get_review

        review = get_review(int(pr_number)) or {}
    except Exception as _rev_exc:  # noqa: BLE001 — doc must persist regardless
        logger.debug("document_pr: get_review failed for #%s: %s", pr_number, _rev_exc)

    summary = (review.get("ai_summary") or "").strip()
    changed, adds, dels = review.get("changed_files"), review.get("additions"), review.get("deletions")
    verdict = review.get("review_status")

    lines = [f"# PR #{pr_number} — {pr_title}", "", f"**Repo:** {repo}  |  **Merged.**"]
    size_bits = []
    if changed is not None:
        size_bits.append(f"{changed} file(s)")
    if adds is not None or dels is not None:
        size_bits.append(f"+{adds or 0} / -{dels or 0}")
    if size_bits:
        lines.append(f"**Size:** {', '.join(size_bits)}")
    if verdict:
        lines.append(f"**F.O.R.G.E. review:** {verdict}")
    if reason:
        lines += ["", f"**Context:** {reason}"]
    if summary:
        lines += ["", "## F.O.R.G.E. review summary", summary]
    lines += ["", f"_Auto-documented via delegate_task(document_pr) on merge of PR #{pr_number}._"]
    content = "\n".join(lines)

    title = f"PR #{pr_number}: {pr_title}"[:200]
    tags = ["pr_doc", "coder_doc", f"pr_{pr_number}", repo.split("/")[-1]]

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                    (knowledge_type, title, content, category, tags, importance_score, source_type)
                VALUES ('vault_note', %s, %s, 'pr_documentation', %s, 0.85, 'delegate_document_pr')
                RETURNING id
                """,
                (title, content, tags),
            )
            row = cur.fetchone()
            kb_id = row["id"] if isinstance(row, dict) else row[0]
        return {
            "success": True,
            "summary": f"Documented PR #{pr_number} -> KB vault_note #{kb_id}",
            "result": {
                "knowledge_base_id": kb_id,
                "pr_number": pr_number,
                "had_review_summary": bool(summary),
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("document_pr: KB insert failed for #%s", pr_number)
        return {"success": False, "summary": f"document_pr KB insert failed: {exc}", "error": str(exc)}


def _execute_known_tool(capability: str, payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Route a known capability to its deterministic service function."""
    if capability == "document_pr":
        return _document_pr(payload, reason)

    if capability in ("run_misroute_audit",):
        from services.misroute_audit_service import run_misroute_audit

        result = run_misroute_audit(window_hours=payload.get("window_hours", 24))
        return {
            "success": True,
            "summary": (
                f"Misroute audit: severity={result['severity']} "
                f"anomalies={result['anomaly_count']} "
                f"window={result['window_hours']}h"
            ),
            "result": result,
        }

    if capability == "run_misroute_to_proposal_adapter":
        from services.misroute_to_proposal_adapter import run as run_adapter

        result = run_adapter(window_hours=payload.get("window_hours", 24))
        return {
            "success": True,
            "summary": (
                f"Misroute adapter: proposals_created={result.get('proposals_created', 0)} "
                f"skipped={result.get('skipped_duplicates', 0)}"
            ),
            "result": result,
        }

    if capability == "run_qa_suite":
        from services.qa_service import run_suite as _run_suite

        suite_id = payload.get("suite_id")
        suite_name = payload.get("suite_name") or payload.get("suite") or "unknown"
        if not suite_id:
            return {"success": False, "summary": "run_qa_suite requires suite_id in args"}
        results = _run_suite(int(suite_id), triggered_by="delegate_task")
        passed = sum(1 for r in results if r.get("status") == "pass")
        failed = sum(1 for r in results if r.get("status") in ("fail", "error"))
        return {
            "success": failed == 0,
            "summary": f"QA suite {suite_name} (#{suite_id}): passed={passed} failed={failed}",
            "result": {"passed": passed, "failed": failed, "total": len(results)},
        }

    if capability in ("health_check", "check_platform_health"):
        from services import health_service

        fn = getattr(health_service, "check_platform_health", None) or getattr(health_service, "health_check", None)
        if fn is None:
            return {
                "success": False,
                "summary": "health_service has no health_check entrypoint",
                "error": "no_entrypoint",
            }
        result = fn()
        return {
            "success": True,
            "summary": "Platform health probed",
            "result": result,
        }

    if capability == "check_dep_drift":
        from services.dep_drift_service import check_dep_drift

        result = check_dep_drift(requirements_path=payload.get("requirements_path"))
        return {
            "success": True,
            "summary": (
                f"Dep drift: missing={len(result.get('missing', []))} "
                f"extra={len(result.get('extra', []))} "
                f"mismatched={len(result.get('mismatched', []))}"
            ),
            "result": result,
        }

    if capability in ("deploy_static", "deploy_vps"):
        from services.deploy_service import run_deploy_pipeline

        result = run_deploy_pipeline(capability, payload)
        return {
            "success": result.success,
            "summary": (
                f"{capability} {payload.get('domain', '?')}: "
                + ("success" if result.success else f"failed — {result.error}")
                + (f" [retried]" if result.retried else "")
                + (f" [rolled_back]" if result.rolled_back else "")
            ),
            "result": {
                "domain": result.domain,
                "backup_id": result.backup_id,
                "retried": result.retried,
                "rolled_back": result.rolled_back,
                "error": result.error,
                "metadata": result.metadata,
            },
        }

    if capability == "translation_coverage_scan":
        # Orchestrator does per-source isolation + ON CONFLICT upserts on
        # translation_gaps (migration 322), and the worker enforces
        # max_instances=1 / coalesce=True — collision with the daily cron at
        # 02:00 UTC is rare and at worst redoes work, never corrupts state.
        from tools.consciousness.translation_scanners.orchestrator import (
            run_translation_coverage_scan,
        )

        summary = run_translation_coverage_scan()
        return {
            "success": True,
            "summary": (
                f"Translation scan: gaps={summary.get('gaps_found', 0)} "
                f"auto_fixed={summary.get('auto_fixed', 0)} "
                f"routed={summary.get('routed', 0)} "
                f"bundles={summary.get('bundles_written', 0)} "
                f"({summary.get('duration_ms', 0)}ms)"
            ),
            "result": summary,
        }

    if capability == "visual_scan":
        # Triggered by P.R.O.B.E. domain translation audit when it detects DOM
        # rendering gaps. Playwright execution is manual (P.R.O.B.E. follows up);
        # this handler logs the request and completes so the worker doesn't block.
        url = payload.get("url", "")
        trigger = payload.get("trigger", reason or "unknown")
        return {
            "success": True,
            "summary": (
                f"visual_scan logged for manual P.R.O.B.E. review: "
                f"trigger={trigger}" + (f" url={url}" if url else "")
            ),
            "result": {
                "url": url,
                "trigger": trigger,
                "queued": True,
                "note": "Playwright visual scan requires manual P.R.O.B.E. follow-up — task auto-completed to unblock worker",
            },
        }

    if capability == "portrait_refinement":
        agent_id = payload.get("agent_id")
        feedback = (payload.get("feedback") or reason or "").strip()
        if not agent_id or not feedback:
            return {
                "success": False,
                "summary": "portrait_refinement requires agent_id and feedback in args",
                "error": "missing_args",
            }
        import psycopg2.extras
        from database import get_db_cursor

        job_meta = psycopg2.extras.Json(
            {
                "agent_id": int(agent_id),
                "feedback": feedback,
                "history": payload.get("history") or [],
                "initiated_by": "mcp_delegate",
            }
        )
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO unified_tasks
                   (title, task_type, status, priority, metadata, tags)
                   VALUES (%s, 'portrait_refinement', 'pending', 7, %s, ARRAY['portrait_refinement','mcp_delegate'])
                   RETURNING id""",
                (f"[Portrait Refine via CLI] Agent {agent_id}: {feedback[:60]}", job_meta),
            )
            task_id = cur.fetchone()["id"]
        return {
            "success": True,
            "summary": f"Portrait refinement queued for agent {agent_id} (task #{task_id})",
            "result": {"task_id": task_id, "agent_id": agent_id, "status": "queued"},
        }

    return {
        "success": False,
        "summary": f"Known-tool capability '{capability}' has no executor",
        "error": "known_but_unwired",
    }


def _execute_via_dispatcher(
    capability: str,
    payload: Dict[str, Any],
    reason: str,
    origin: str = "mcp_client",
) -> Dict[str, Any]:
    """Fallback: hand to the Department HQ dispatcher.

    Constructs a natural-language prompt so the LLM agent picked by
    ``smart_router`` gets the full context, not just a capability tag.

    Wraps the dispatch in ``claude_request(mcp_tool='delegate_task',
    origin=origin)`` so the resulting ``task_execution_log`` row is
    tagged with ``request_origin`` matching the delegation_source.
    Without this, the ContextVar set by the original MCP handler is
    lost across the async worker boundary, and Claude-delegated rows
    show up as un-attributed in the DHQ Claude Requests panel.
    """
    from tools.department_hq.services.department_dispatcher import dispatch

    # Lazy import — keeps delegation_service usable even if the MCP
    # subpackage is unavailable (e.g. in tests). claude_request is a
    # no-op context manager when mcp_server is missing.
    try:
        from mcp_server.dispatch_context import claude_request
    except Exception:
        from contextlib import contextmanager

        @contextmanager
        def claude_request(mcp_tool: str, origin: str = "claude"):  # type: ignore[no-redef]
            yield

    prompt_lines = [f"Delegated task — capability: {capability}"]
    if reason:
        prompt_lines.append(f"Reason: {reason}")
    if payload:
        prompt_lines.append(f"Args: {json.dumps(payload)[:500]}")
    prompt = "\n".join(prompt_lines)

    with claude_request(mcp_tool="delegate_task", origin=origin):
        dispatch_result = dispatch(
            capability=capability,
            prompt=prompt,
            module_id="delegation_service",
        )
    if not dispatch_result.success:
        return {
            "success": False,
            "summary": f"Dispatcher refused: {dispatch_result.error or 'unknown'}",
            "error": dispatch_result.error or "dispatch_failed",
        }

    return {
        "success": True,
        "summary": (
            f"Dispatched to agent={dispatch_result.agent_name or 'unknown'} "
            f"model={dispatch_result.model_used or 'unknown'}"
        ),
        "result": {
            "response": getattr(dispatch_result, "response", None),
            "agent": dispatch_result.agent_name,
            "model": dispatch_result.model_used,
            "tier": getattr(dispatch_result, "tier", None),
            "cost_usd": getattr(dispatch_result, "cost_usd", None),
        },
    }


def emit_delegation_event(
    task_id: int,
    event_type: str,
    capability: str,
    summary: str = "",
    delegation_source: str = "mcp_client",
    streaming_channel: Optional[str] = None,
) -> None:
    """Fire a delegation lifecycle event into Unified Comms (#265).

    Routes through ``telegram_service.send_info`` in A.R.C.H.I.E.'s
    direct voice (Executive Office, COO tone), since delegated work is
    Archie executing on Kytran's / Claude's behalf.

    ``streaming_channel`` is honored as a targeting hint (e.g. a
    specific Telegram chat or comms conversation). For now the default
    chat_id from ``telegram_service`` is used unless the channel
    encodes ``telegram:<chat_id>`` — keeps Phase 3 scope small while
    leaving room for multi-channel routing in Phase 4.

    This function NEVER raises. Streaming is best-effort; a dead
    Telegram bridge must not block worker progress.

    event_type: one of ``start``, ``complete``, ``fail``.
    """
    try:
        import threading

        from services import telegram_service  # local import — avoids boot cycle

        verb = {
            "start": "picking up",
            "complete": "completed",
            "fail": "failed",
        }.get(event_type, event_type)

        title = f"Delegated task #{task_id} {verb}"
        body_lines = [
            f"Capability: {capability}",
            f"Source: {delegation_source}",
        ]
        if summary:
            body_lines.append(f"Result: {summary}")
        message = "\n".join(body_lines)

        send_kwargs: Dict[str, Any] = {}
        if streaming_channel and streaming_channel.startswith("telegram:"):
            send_kwargs["chat_id"] = streaming_channel.split(":", 1)[1] or None

        # Failure events escalate via send_system (warning priority);
        # start/complete stay informational. Both can hit the
        # director_reports inbox HTTP path which has been observed
        # to take 30–60s when the comms bridge is slow.
        #
        # Fire-and-forget on a daemon thread: returns immediately, the
        # thread runs to completion (or never; daemon=True means it
        # won't block process shutdown). PR #497 used a
        # ThreadPoolExecutor with a 5s future timeout, but the `with`
        # block then called shutdown(wait=True) which blocked anyway
        # — defeating the timeout. Streaming is best-effort, so a
        # cleaner approach is "do not wait for it at all."
        send_fn = telegram_service.send_system if event_type == "fail" else telegram_service.send_info

        def _send_fire_and_forget() -> None:
            try:
                send_fn(title, message, **send_kwargs)
            except Exception as inner_exc:
                logger.debug(
                    "emit_delegation_event background send failed (task=%s event=%s): %s",
                    task_id,
                    event_type,
                    inner_exc,
                )

        threading.Thread(
            target=_send_fire_and_forget,
            name=f"delegate-emit-{task_id}-{event_type}",
            daemon=True,
        ).start()
    except Exception as exc:
        # Streaming must never break the worker loop. Log and move on.
        logger.warning(
            "emit_delegation_event(task=%s event=%s) suppressed error: %s",
            task_id,
            event_type,
            exc,
        )


def fetch_pending_delegations(limit: int = 10) -> list:
    """Return up to ``limit`` pending delegated tasks oldest-first."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, title, description, priority, delegation_source,
                   delegation_args, streaming_channel
            FROM unified_tasks
            WHERE delegation_source IS NOT NULL
              AND status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_task_in_progress(task_id: int) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE unified_tasks SET status = 'in_progress' WHERE id = %s",
            (task_id,),
        )


def mark_task_completed(task_id: int, summary: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE unified_tasks SET status = 'completed', completed_at = now() WHERE id = %s",
            (task_id,),
        )
        cur.execute(
            """
            INSERT INTO work_notes (task_id, note_type, content, metadata)
            VALUES (%s, 'delegation_result', %s, %s::jsonb)
            """,
            (task_id, summary, json.dumps({"outcome": "completed"})),
        )


def mark_task_failed(task_id: int, error: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE unified_tasks SET status = 'blocked' WHERE id = %s",
            (task_id,),
        )
        cur.execute(
            """
            INSERT INTO work_notes (task_id, note_type, content, metadata)
            VALUES (%s, 'delegation_failure', %s, %s::jsonb)
            """,
            (task_id, error, json.dumps({"outcome": "failed"})),
        )
