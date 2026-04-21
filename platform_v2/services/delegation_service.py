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

        if not capability:
            return {
                "success": False,
                "summary": "No capability in delegation_args",
                "error": "missing_capability",
            }

        if capability in KNOWN_TOOL_CAPABILITIES:
            return _execute_known_tool(capability, payload, reason)

        return _execute_via_dispatcher(capability, payload, reason)
    except Exception as exc:
        logger.exception("execute_delegated_task failed for task #%s", task.get("id"))
        return {
            "success": False,
            "summary": f"Executor raised: {type(exc).__name__}: {exc}",
            "error": str(exc),
        }


def _execute_known_tool(capability: str, payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Route a known capability to its deterministic service function."""
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
        # qa_service lives inside platform_v2/tools/probe/... — import lazily
        # to avoid pulling PROBE on every delegation service import.
        from services.qa_service import run_qa_suite as _run_qa

        suite_name = payload.get("suite_name") or payload.get("suite") or "default"
        result = _run_qa(suite_name=suite_name)
        return {
            "success": bool(result.get("success")),
            "summary": (
                f"QA suite {suite_name}: passed={result.get('passed', 0)} " f"failed={result.get('failed', 0)}"
            ),
            "result": result,
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

    return {
        "success": False,
        "summary": f"Known-tool capability '{capability}' has no executor",
        "error": "known_but_unwired",
    }


def _execute_via_dispatcher(capability: str, payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Fallback: hand to the Department HQ dispatcher.

    Constructs a natural-language prompt so the LLM agent picked by
    ``smart_router`` gets the full context, not just a capability tag.
    """
    from tools.department_hq.services.department_dispatcher import dispatch

    prompt_lines = [f"Delegated task — capability: {capability}"]
    if reason:
        prompt_lines.append(f"Reason: {reason}")
    if payload:
        prompt_lines.append(f"Args: {json.dumps(payload)[:500]}")
    prompt = "\n".join(prompt_lines)

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
        # start/complete stay informational.
        if event_type == "fail":
            telegram_service.send_system(title, message, **send_kwargs)
        else:
            telegram_service.send_info(title, message, **send_kwargs)
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
