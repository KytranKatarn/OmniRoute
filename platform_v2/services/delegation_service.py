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
import os
import time
from typing import Any, Dict, List, Optional

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
    "run_briefing_health",  # P.R.O.B.E. — run all agent chat briefings, flag schema drift
    "run_misroute_to_proposal_adapter",
    "deploy_static",
    "deploy_vps",
    "external_fetch",
    "capture_chat_share",  # S.C.O.U.T. — render a public AI chat share link into Mailbox Story
    "portrait_refinement",
    "translation_coverage_scan",
    "visual_scan",  # P.R.O.B.E. Playwright visual verification — logs and completes
    "document_pr",  # persist a coder-doc vault_note for a merged PR (deterministic store)
    "restore_sandbox",  # W.A.R.D.E.N. — real pg_restore into the disposable staging DB (#4050)
    "restore_production",  # W.A.R.D.E.N. — promote (host-gated, ADR-001) (#4050)
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

    # Phase B: a codex_task is NOT cluster work — Codex (an external CLI coding
    # agent) cannot run on Ollama. It is created 'deferred' so the pending-only
    # delegate_task_worker never claims it; the host poller
    # (scripts/agents/codex-delegation-worker.sh) reads 'deferred' codex rows,
    # composes a prompt (project + task context) and runs the sandboxed Codex
    # runner. Everything else stays 'pending' for the normal worker.
    is_codex = capability == "codex_task"
    status = "deferred" if is_codex else "pending"
    task_metadata = {"codex": True, "project_id": project_id} if is_codex else None

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO unified_tasks
                (project_id, title, description, status, priority, task_type,
                 delegation_source, delegation_args, streaming_channel, metadata)
            VALUES (%s, %s, %s, %s, %s, 'implementation',
                    %s, %s::jsonb, %s, %s::jsonb)
            RETURNING id
            """,
            (
                project_id,
                title,
                f"Delegated by {requested_by} via {delegation_source}: {reason}",
                status,
                priority,
                delegation_source,
                json.dumps(delegation_args),
                streaming_channel,
                json.dumps(task_metadata) if task_metadata else None,
            ),
        )
        task_id = cur.fetchone()["id"]

    logger.info(
        "Delegated task #%d: capability=%s source=%s status=%s requested_by=%s",
        task_id,
        capability,
        delegation_source,
        status,
        requested_by,
    )
    return {
        "success": True,
        "task_id": task_id,
        "title": title,
        "uses_known_tool": capability in KNOWN_TOOL_CAPABILITIES,
        "deferred_to": "codex" if is_codex else None,
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
            if isinstance(payload, dict):
                payload = {**payload, "_task_id": task.get("id")}
            return _execute_known_tool(capability, payload, reason)

        return _execute_via_dispatcher(capability, payload, reason, origin=delegation_source, task_id=task.get("id"))
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
            # Idempotent upsert: re-documenting an already-documented PR must be a
            # harmless refresh, NOT a hard failure. A plain INSERT tripped the
            # partial unique index idx_kb_title_unique (title WHERE title IS NOT
            # NULL) and false-blocked the delegated task (e.g. PR #1384 re-queue).
            cur.execute(
                """
                INSERT INTO knowledge_base
                    (knowledge_type, title, content, category, tags, importance_score, source_type)
                VALUES ('vault_note', %s, %s, 'pr_documentation', %s, 0.85, 'delegate_document_pr')
                ON CONFLICT (title) WHERE title IS NOT NULL
                DO UPDATE SET
                    content = EXCLUDED.content,
                    category = EXCLUDED.category,
                    tags = EXCLUDED.tags,
                    source_type = EXCLUDED.source_type,
                    updated_at = NOW()
                RETURNING id, (xmax = 0) AS inserted
                """,
                (title, content, tags),
            )
            row = cur.fetchone()
            if isinstance(row, dict):
                kb_id, was_insert = row["id"], row["inserted"]
            else:
                kb_id, was_insert = row[0], row[1]
        verb = "Documented" if was_insert else "Refreshed doc for"
        return {
            "success": True,
            "summary": f"{verb} PR #{pr_number} -> KB vault_note #{kb_id}",
            "result": {
                "knowledge_base_id": kb_id,
                "pr_number": pr_number,
                "had_review_summary": bool(summary),
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("document_pr: KB insert failed for #%s", pr_number)
        return {"success": False, "summary": f"document_pr KB insert failed: {exc}", "error": str(exc)}


def _persist_dispatched_documentation(reason: str, payload: Dict[str, Any], response: Optional[str]) -> Optional[int]:
    """Persist LLM-generated documentation (non-PR delegations) as a vault_note.

    The dispatcher path (``_execute_via_dispatcher``) returns the generated doc
    text in ``dispatch_result.response``, but the worker only writes a short
    summary to ``work_notes`` — the actual doc was NEVER stored in the KB
    (#3553), so general ``capability='documentation'`` delegations produced no
    searchable docs even when the task completed. PR docs use the deterministic
    ``_document_pr`` path; everything else lands here. Persist so the doc shows
    up in Consciousness like any other vault_note. Best-effort: a KB-insert
    failure must not fail the delegation (the dispatch already succeeded).
    """
    text = (response or "").strip()
    if not text:
        return None

    # Title precedence: explicit arg > the doc's own first heading/line >
    # first line of the delegation reason > generic. Deriving from the
    # generated doc keeps the title consistent with its content (F.O.R.G.E.
    # review on #1317 flagged reason-only derivation as inconsistent).
    def _first_meaningful_line(s: Optional[str]) -> str:
        for ln in (s or "").splitlines():
            cleaned = ln.strip().lstrip("#").strip()
            if cleaned:
                return cleaned
        return ""

    title = (
        payload.get("title")
        or _first_meaningful_line(text)
        or _first_meaningful_line(reason)
        or "Delegated documentation"
    ).strip()[:200]
    tags = ["coder_doc", "delegated_doc", "documentation"]
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                    (knowledge_type, title, content, category, tags, importance_score, source_type)
                VALUES ('vault_note', %s, %s, 'delegated_documentation', %s, 0.8, 'delegate_documentation')
                RETURNING id
                """,
                (title, text, tags),
            )
            row = cur.fetchone()
            return row["id"] if isinstance(row, dict) else row[0]
    except Exception:  # noqa: BLE001 — doc persistence must not fail the delegation
        logger.exception("_persist_dispatched_documentation: KB insert failed")
        return None


def _execute_known_tool(capability: str, payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Route a known capability to its deterministic service function."""
    if capability == "document_pr":
        return _document_pr(payload, reason)

    if capability == "restore_sandbox":
        from services.backup_restore_service import run_sandbox_restore

        return run_sandbox_restore(backup_id=payload.get("backup_id"), session_id=payload.get("session_id"))

    if capability == "restore_production":
        from services.backup_restore_service import run_production_restore

        return run_production_restore(session_id=payload.get("session_id"), backup_id=payload.get("backup_id"))

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
        # Host-side Playwright UI suite: if a module with a pytest test file is
        # named, ENQUEUE it for the host runner (the container has no chromium) and
        # let scripts/run_ui_qa_queue.py drive the real browser test + post results
        # back to this task. Non-UI delegations keep the in-container API path. #371
        import os as _os
        import re as _re

        ui_module = payload.get("module") or payload.get("suite_name")
        if (
            ui_module
            and _re.fullmatch(r"[a-z0-9_]{1,64}", ui_module)
            and _os.path.isfile(f"/app/qa/tests/modules/{ui_module}.py")
        ):
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO ui_qa_queue (module, requested_by, task_id, status) "
                    "VALUES (%s, %s, %s, 'queued') RETURNING id",
                    (ui_module, payload.get("requested_by") or "delegate_task", payload.get("_task_id")),
                )
                row = cur.fetchone()
                qid = row["id"] if isinstance(row, dict) else row[0]
            return {
                "success": True,
                "summary": f"UI QA '{ui_module}' queued for the host Playwright runner (queue #{qid}); results post back to this task.",
            }

        from services.qa_service import run_suite as _run_suite

        suite_id = payload.get("suite_id")
        suite_name = payload.get("suite_name") or payload.get("suite") or "unknown"
        if not suite_id:
            # No specific suite → run ALL active suites and aggregate. This is
            # the "full health scan" intent (e.g. post-DR-test). It used to hard
            # fail with "requires suite_id", which left the task blocked and
            # escalated a Telegram warning forever. The SCAN COMPLETING is the
            # success criterion here — individual test failures are reported as
            # data, not as a delegation failure (a 75-suite scan almost always
            # has some red, and that should not block/escalate the task).
            from services.qa_service import get_suites as _get_suites

            suites = _get_suites()
            if not suites:
                return {"success": False, "summary": "run_qa_suite: no active QA suites to run"}
            total_passed = total_failed = total_tests = 0
            ran = 0
            per_suite = []
            for s in suites:
                sid = s.get("id")
                sname = s.get("name") or f"#{sid}"
                try:
                    results = _run_suite(int(sid), triggered_by="delegate_task")
                except Exception as exc:
                    per_suite.append(f"{sname}#{sid}: ERROR {type(exc).__name__}")
                    logger.warning("run_qa_suite all-scan: suite %s failed: %s", sid, exc)
                    continue
                p = sum(1 for r in results if r.get("status") == "pass")
                f = sum(1 for r in results if r.get("status") in ("fail", "error"))
                total_passed += p
                total_failed += f
                total_tests += len(results)
                ran += 1
                if f:
                    per_suite.append(f"{sname}#{sid}: {p}/{p + f}")
            red = ", ".join(per_suite[:15]) if per_suite else "none"
            return {
                # Success = the scan ran. Failures are reported, not escalated.
                "success": ran > 0,
                "summary": (
                    f"QA full scan: {ran}/{len(suites)} suites ran, "
                    f"passed={total_passed} failed={total_failed} (suites with red: {red})"
                ),
                "result": {
                    "suites_ran": ran,
                    "suites_total": len(suites),
                    "passed": total_passed,
                    "failed": total_failed,
                    "total": total_tests,
                    "suites_with_failures": per_suite,
                },
            }
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

    if capability == "run_briefing_health":
        from services.briefing_health_service import check_briefing_health

        result = check_briefing_health()
        return {
            "success": result["severity"] == "ok",
            "summary": (
                f"Briefing health: {result['ok']}/{result['total']} OK"
                + ("" if not result["failed"] else " — broken: " + ", ".join(f["module"] for f in result["failed"]))
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

    if capability == "external_fetch":
        import os as _os

        import requests as _req

        url = (payload.get("url") or "").strip()
        if not url:
            return {"success": False, "summary": "external_fetch: url is required"}

        region = payload.get("region") or payload.get("preferred_region")
        prefer_residential = payload.get("prefer_residential", True)
        method = (payload.get("method") or "GET").upper()
        extra_headers = payload.get("headers") or {}
        body = payload.get("body")
        timeout = min(int(payload.get("timeout") or 30), 120)

        from services.fleet_resource_router import find_best_egress_node

        best_node_id = find_best_egress_node(preferred_region=region, prefer_residential=prefer_residential)

        # Hub cluster_proxy is the only deployed proxy endpoint today.
        # When outpost node_api gains /api/proxy/fetch, route to mesh IP of best_node_id instead.
        proxy_key = _os.environ.get("CLUSTER_PROXY_KEY", "")
        proxy_url = "http://127.0.0.1:3000/api/proxy/fetch"

        try:
            resp = _req.post(
                proxy_url,
                json={"url": url, "method": method, "headers": extra_headers, "body": body, "timeout": timeout},
                headers={"X-Proxy-Key": proxy_key},
                timeout=timeout + 10,
            )
            data = resp.json() if "application/json" in resp.headers.get("Content-Type", "") else {}
            ok = resp.status_code == 200 and not data.get("error")
            return {
                "success": ok,
                "summary": (
                    f"external_fetch {method} {url[:60]} → "
                    f"{data.get('status_code', resp.status_code)} "
                    f"({data.get('elapsed_ms', 0)}ms) via node={best_node_id}"
                ),
                "result": data,
            }
        except Exception as exc:
            return {"success": False, "summary": f"external_fetch failed: {exc}"}

    if capability == "capture_chat_share":
        url = (payload.get("url") or payload.get("target_url") or "").strip()
        if not url:
            return {"success": False, "summary": "capture_chat_share: url is required"}
        from services.mailbox_scout_capture import capture_share

        res = capture_share(
            url,
            owner_id=payload.get("owner_id"),
            title=payload.get("title"),
            timeout_s=min(int(payload.get("timeout") or 120), 240),
        )
        ok = bool(res.get("import_id"))
        return {
            "success": ok,
            "summary": (
                f"capture_chat_share {url[:60]} → import {res['import_id']} " f"({res['messages']} messages)"
                if ok
                else f"capture_chat_share failed: {res.get('error')}"
            ),
            "result": res,
        }

    if capability == "translation_coverage_scan":
        # Orchestrator does per-source isolation + ON CONFLICT upserts on
        # translation_gaps (migration 322); the worker enforces
        # max_instances=1 / coalesce=True.
        #
        # A git-hook trigger names the changed website/i18n file(s): scope the
        # scan to just the affected source(s) and skip the heavy global passes
        # (LLM generation, live domain audit, deploy) — that work belongs to the
        # nightly cron. This keeps the delegate fast (seconds vs. the ~73-min
        # full scan that false-blocked at the 360s worker timeout and wedged the
        # single-instance worker). Non-git-hook callers run the full scan.
        from tools.consciousness.translation_scanners.orchestrator import (
            run_translation_coverage_scan,
        )

        scoped_sources = None
        scan_kwargs: dict = {}
        scope_note = "full"
        if payload.get("trigger") == "git_hook":
            scoped_sources = _match_scan_sources(payload.get("changed_paths") or [])
            if scoped_sources:
                scan_kwargs = {"generate": False, "domain_audit": False, "deploy": False}
                scope_note = "scoped:" + ",".join(e[0] for e in scoped_sources)

        summary = run_translation_coverage_scan(sources=scoped_sources, **scan_kwargs)
        return {
            "success": True,
            "summary": (
                f"Translation scan ({scope_note}): "
                f"gaps={summary.get('gaps_found', 0)} "
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


def _match_scan_sources(changed_paths: list) -> list:
    """Map git-changed repo-relative paths → EXTERNAL_SCAN_SOURCES entries.

    Lets a git-hook translation scan run only the source(s) whose files
    changed. Returns the matching (label, directory, bundle_path) tuples;
    empty list if nothing maps (caller then falls back to a full scan).
    """
    try:
        from tools.consciousness.language_routes import EXTERNAL_SCAN_SOURCES
    except Exception:  # noqa: BLE001
        return []
    repo_root = "/mnt/archie_brain"
    abs_paths = [os.path.join(repo_root, p) for p in changed_paths if p]
    matched = []
    for entry in EXTERNAL_SCAN_SOURCES:
        directory = entry[1]
        prefix = directory.rstrip("/") + "/"
        if any(ap == directory or ap.startswith(prefix) for ap in abs_paths):
            matched.append(entry)
    return matched


def _execute_via_dispatcher(
    capability: str,
    payload: Dict[str, Any],
    reason: str,
    origin: str = "mcp_client",
    task_id: Optional[int] = None,
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
    # Layer-3 fix (#269999): a cold model returns queued=True with a
    # dispatch_pending_queue id — the work is enqueued, NOT failed. Attach a
    # result-callback so model_dispatch_worker writes the output back to this
    # task when the model warms/completes (or marks it blocked on failure), and
    # report 'queued' so the worker leaves the task in_progress rather than
    # false-blocking it (the bug that orphaned tasks #3636/#3637).
    if getattr(dispatch_result, "queued", False):
        qid = getattr(dispatch_result, "queue_id", None)
        if task_id and qid:
            _attach_delegation_callback(qid, task_id, capability, reason)
        return {
            "success": False,
            "queued": True,
            "summary": (
                f"Queued to fleet (queue #{qid}, "
                f"{dispatch_result.model_used or 'model'} warming) — completes async via callback"
            ),
            "result": {"queue_id": qid, "status": "queued"},
        }
    if not dispatch_result.success:
        return {
            "success": False,
            "summary": f"Dispatcher refused: {dispatch_result.error or 'unknown'}",
            "error": dispatch_result.error or "dispatch_failed",
        }

    response = getattr(dispatch_result, "response", None)
    summary = (
        f"Dispatched to agent={dispatch_result.agent_name or 'unknown'} "
        f"model={dispatch_result.model_used or 'unknown'}"
    )

    # #3553: persist the generated doc as a vault_note. The dispatcher returns
    # the doc text in `response`, but the worker only writes `summary` to
    # work_notes — so general documentation delegations (no pr_number, which
    # would route to the deterministic _document_pr path instead) produced no
    # searchable KB entry even on success. Gated to documentation; best-effort.
    kb_id = None
    if capability == "documentation":
        kb_id = _persist_dispatched_documentation(reason, payload, response)
        if kb_id:
            summary += f" -> KB vault_note #{kb_id}"

    return {
        "success": True,
        "summary": summary,
        "result": {
            "response": response,
            "knowledge_base_id": kb_id,
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
            "UPDATE unified_tasks SET status = 'in_progress', updated_at = now() WHERE id = %s",
            (task_id,),
        )


def reclaim_stale_delegations(exclude_ids, idle_secs: int = 600, limit: int = 10) -> Dict[str, int]:
    """Rescue delegation tasks stuck in ``in_progress`` with no activity.

    A scheduler restart wipes the worker's in-memory carry-over list, so any
    task the previous worker was executing is abandoned as ``in_progress`` with
    nothing left to finish or fail it — it sits forever (observed: a doc task
    stuck 237h). This reclaims those orphans: reset to ``pending`` for a fresh
    attempt, or — after repeated reclaims — mark ``blocked`` so it can't loop.

    Safety:
      * ``exclude_ids`` = task ids the LIVE worker is currently tracking
        (its inflight set) — never reclaim those (would double-execute).
      * Only tasks with NO ``work_notes`` activity in the idle window are
        eligible — this skips tasks legitimately awaiting an async cold-load
        callback (they carry a recent ``delegation_queued`` note).
      * ``updated_at`` clock is reset on each (re)claim, so a retried task gets
        a full idle window before it could be reclaimed again.
    """
    exclude_ids = [int(x) for x in (exclude_ids or [])]
    reclaimed = gave_up = 0
    base_where = (
        "delegation_source IS NOT NULL AND status = 'in_progress' "
        "AND updated_at < now() - make_interval(secs => %s) "
        "AND NOT EXISTS (SELECT 1 FROM work_notes w "
        "WHERE w.task_id = t.id AND w.created_at > now() - make_interval(secs => %s))"
    )
    with get_db_cursor(commit=True) as (conn, cur):
        if exclude_ids:
            cur.execute(
                f"SELECT id FROM unified_tasks t WHERE {base_where} " "AND id <> ALL(%s) ORDER BY updated_at LIMIT %s",
                (idle_secs, idle_secs, exclude_ids, limit),
            )
        else:
            cur.execute(
                f"SELECT id FROM unified_tasks t WHERE {base_where} " "ORDER BY updated_at LIMIT %s",
                (idle_secs, idle_secs, limit),
            )
        ids = [r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        for tid in ids:
            cur.execute(
                "SELECT count(*) AS c FROM work_notes " "WHERE task_id = %s AND note_type = 'delegation_reclaimed'",
                (tid,),
            )
            row = cur.fetchone()
            prior = row["c"] if isinstance(row, dict) else row[0]
            if prior >= 2:
                cur.execute(
                    "UPDATE unified_tasks SET status = 'blocked', updated_at = now() WHERE id = %s",
                    (tid,),
                )
                note = f"Gave up reclaiming stale in_progress task after {prior} attempts"
                gave_up += 1
            else:
                cur.execute(
                    "UPDATE unified_tasks SET status = 'pending', updated_at = now() WHERE id = %s",
                    (tid,),
                )
                note = f"Reclaimed stale in_progress task (orphaned, attempt {prior + 1})"
                reclaimed += 1
            cur.execute(
                "INSERT INTO work_notes (task_id, note_type, content, metadata) "
                "VALUES (%s, 'delegation_reclaimed', %s, %s::jsonb)",
                (tid, note, json.dumps({"prior_reclaims": prior})),
            )
    if reclaimed or gave_up:
        logger.info("reclaim_stale_delegations: reclaimed=%d gave_up=%d", reclaimed, gave_up)
    return {"reclaimed": reclaimed, "gave_up": gave_up}


def _attach_delegation_callback(queue_id: int, task_id: int, capability: str, reason: str) -> None:
    """Attach a ``delegation_result`` callback to a queued dispatch row.

    When ``model_dispatch_worker`` finishes the cold-load job,
    ``_handle_callback`` (model_dispatch_service) writes the response back to
    this unified_task and flips it completed/blocked. Only updates rows still
    awaiting execution so we never clobber a row that already finished in the
    (tiny) race window between dispatch returning and this UPDATE.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                   SET callback_type = 'delegation_result',
                       callback_data = %s::jsonb
                 WHERE id = %s AND status IN ('queued', 'running')
                """,
                (
                    json.dumps(
                        {
                            "task_id": task_id,
                            "capability": capability,
                            "reason": (reason or "")[:200],
                        }
                    ),
                    queue_id,
                ),
            )
    except Exception as exc:
        logger.warning("Failed to attach delegation callback to queue #%s: %s", queue_id, exc)


def mark_task_queued(task_id: int, summary: str) -> None:
    """Record that a delegated task was deferred to the cold-load queue.

    Leaves status as ``in_progress`` (the worker set it before dispatch) and
    adds a lifecycle note. The dispatch_pending_queue callback later flips the
    task to completed/blocked — so we must NOT mark it failed here.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO work_notes (task_id, note_type, content, metadata)
            VALUES (%s, 'delegation_queued', %s, %s::jsonb)
            """,
            (task_id, summary, json.dumps({"outcome": "queued"})),
        )


# --- #4167: surface delegated output on the task + flag code-as-advisory ------
# Delegation results are persisted to the work_notes TABLE (note_type=
# 'delegation_output'), which is invisible on the unified_task itself —
# unified_tasks.metadata stayed empty, so a completed delegation looked like
# "nothing happened" (it caused a real misdiagnosis, KB #273387). And a
# capability='code' delegation returns TEXT instructions, never a branch/PR,
# so its result must never read as a shipped code change.
CODE_MERGE_CAPABILITIES = {"code"}

_CODE_ADVISORY = (
    "ADVISORY ONLY — fleet code delegation produces analysis/instructions, NOT a "
    "branch or PR. No code change was shipped; implement it via a Claude/human PR."
)


def build_delegation_metadata(
    capability: Optional[str], response: Optional[str], outcome: str = "completed", via: str = None
) -> Dict[str, Any]:
    """Pure helper: build the ``delegation`` block merged into
    ``unified_tasks.metadata`` on completion so a delegated task SURFACES its
    result (preview + pointer to the full text in the work_notes table) instead
    of burying it. Adds an advisory for code-merge capabilities (#4167)."""
    resp = (response or "").strip()
    block: Dict[str, Any] = {
        "outcome": outcome,
        "capability": capability or "unknown",
        "result_chars": len(resp),
        "result_note_type": "delegation_output",  # full text lives in the work_notes table
        "result_preview": resp[:280],
    }
    if via:
        block["via"] = via
    if capability in CODE_MERGE_CAPABILITIES:
        block["advisory"] = _CODE_ADVISORY
    return block


def mark_task_completed(task_id: int, summary: str, response: str = None, capability: str = None) -> None:
    deleg_meta = build_delegation_metadata(capability, response, outcome="completed")
    # Prepend the advisory so a code delegation is never mistaken for a shipped
    # change, even when only the work_notes lifecycle line is read.
    note = f"⚠️ {deleg_meta['advisory']}\n\n{summary}" if deleg_meta.get("advisory") else summary
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE unified_tasks "
            "SET status = 'completed', completed_at = now(), "
            "    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('delegation', %s::jsonb) "
            "WHERE id = %s",
            (json.dumps(deleg_meta), task_id),
        )
        # Lifecycle note (the short "Dispatched to agent=X" summary).
        cur.execute(
            """
            INSERT INTO work_notes (task_id, note_type, content, metadata)
            VALUES (%s, 'delegation_result', %s, %s::jsonb)
            """,
            (task_id, note, json.dumps({"outcome": "completed"})),
        )
        # #269999: persist the agent's ACTUAL output too, so delegated
        # analysis/research/audit work is captured — not just the dispatch stub.
        resp = (response or "").strip()
        if resp:
            cur.execute(
                """
                INSERT INTO work_notes (task_id, note_type, content, metadata)
                VALUES (%s, 'delegation_output', %s, %s::jsonb)
                """,
                (task_id, resp[:20000], json.dumps({"outcome": "completed", "chars": len(resp)})),
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


# ----------------------------------------------------------------------
# Concurrent draining engine (Project #375 / handoff 2026-06-08)
# ----------------------------------------------------------------------
# The agent-loop worker used to drain delegations SERIALLY: a pool with
# max_workers=1 plus a submit→future.result()→next loop meant one slow
# 7B task (documentation, up to 660s) blocked every task behind it. With
# 8 doc tasks queued that is ~40 minutes of head-of-line blocking per
# task. ``run_delegation_cycle`` runs the claimed tasks CONCURRENTLY in a
# bounded pool while preserving every safety property of the old loop:
#
#   * per-capability timeout shield (a hung layer never freezes the job),
#   * the ``queued`` cold-load defer path (rows stay in_progress; the
#     dispatch_pending_queue callback finishes them — #3636/#3637),
#   * no double-claim (the caller keeps APScheduler ``max_instances=1``;
#     claiming is non-atomic, so cycles must not overlap),
#   * no ThreadPoolExecutor clog: a future that overruns its REAL
#     deadline is marked blocked (retry-able) but KEEPS occupying its
#     logical slot until the thread actually dies, so we never oversubmit
#     into a pool whose workers are all stuck.
#
# State the caller owns and threads back in every cycle:
#   pool      — a ThreadPoolExecutor(max_workers=concurrency), reused.
#   inflight  — a list of carry-over entries (futures still running from
#               a previous cycle). Mutated in place.


def _parse_capability(task: Dict[str, Any]) -> str:
    """Best-effort extract the ``capability`` string from a task row."""
    args = task.get("delegation_args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if isinstance(args, dict):
        return args.get("capability", "unknown")
    return "unknown"


def run_delegation_cycle(
    pool,
    inflight: List[Dict[str, Any]],
    *,
    concurrency: int,
    cycle_budget_secs: float,
    capability_timeouts: Dict[str, int],
    default_timeout: int,
    log_cycle=None,
    reclaim_idle_secs: int = 600,
    reclaim_limit: int = 10,
    _now=time.time,
) -> Dict[str, int]:
    """Run ONE concurrent draining cycle. Returns a stats dict.

    ``pool`` and ``inflight`` are persistent state owned by the caller (the
    agent-loop worker) so carry-over futures survive between 30s cycles.
    Every delegation_service helper is called by name (not injected) so the
    unit test can patch them exactly like the rest of the suite.
    """
    from concurrent.futures import FIRST_COMPLETED
    from concurrent.futures import wait as _futures_wait

    stats = {"claimed": 0, "completed": 0, "failed": 0, "queued": 0, "carried": 0}

    def _handle_done(entry: Dict[str, Any]) -> None:
        """Apply the real result of a finished future (completed/failed/queued)."""
        task_id = entry["task_id"]
        capability = entry["capability"]
        source = entry["source"]
        channel = entry["channel"]
        try:
            result = entry["future"].result()
        except Exception as exc:  # executor raised
            logger.exception("Delegate task #%s raised during execute", task_id)
            _safe(mark_task_failed, task_id, f"Executor exception: {exc}")
            _safe_emit(task_id, "fail", capability, f"Executor exception: {exc}", source, channel)
            stats["failed"] += 1
            return

        if result.get("queued"):
            # Cold-load defer (#269999): leave in_progress, the
            # dispatch_pending_queue callback flips it later. NEVER fail it.
            _safe(mark_task_queued, task_id, result.get("summary", ""))
            logger.info("Delegate task #%s queued to fleet (async)", task_id)
            stats["queued"] += 1
        elif result.get("success"):
            summary = result.get("summary", "")
            resp = (result.get("result") or {}).get("response")
            _safe(mark_task_completed, task_id, summary, response=resp, capability=capability)
            _safe_emit(task_id, "complete", capability, summary, source, channel)
            stats["completed"] += 1
        else:
            fail_summary = result.get("summary") or result.get("error") or "Unknown failure"
            _safe(mark_task_failed, task_id, fail_summary)
            _safe_emit(task_id, "fail", capability, fail_summary, source, channel)
            stats["failed"] += 1

    def _safe(fn, *a, **kw) -> None:
        try:
            fn(*a, **kw)
        except Exception:
            logger.exception("delegation cycle: %s failed", getattr(fn, "__name__", fn))

    def _safe_emit(task_id, event, capability, summary, source, channel) -> None:
        try:
            emit_delegation_event(
                task_id,
                event,
                capability=capability,
                summary=summary,
                delegation_source=source,
                streaming_channel=channel,
            )
        except Exception:
            pass

    # 0) Rescue orphans: tasks stuck in_progress with no activity (e.g. abandoned
    #    when a scheduler restart wiped this list). Exclude the live inflight set
    #    so we never reclaim something this worker is actively running.
    live_ids = [e["task_id"] for e in inflight]
    try:
        reclaim_stale_delegations(live_ids, idle_secs=reclaim_idle_secs, limit=reclaim_limit)
    except Exception:
        logger.exception("delegation cycle: reclaim_stale_delegations failed")

    # 1) Advance carry-over futures from previous cycles. A still-running
    #    future keeps its slot busy; one past its REAL deadline is marked
    #    blocked once but kept until the thread truly finishes (no clog).
    still: List[Dict[str, Any]] = []
    for entry in inflight:
        fut = entry["future"]
        if fut.done():
            if not entry.get("marked_blocked"):
                _handle_done(entry)
            # else: already blocked on a prior cycle — discard the late result.
            continue
        if _now() > entry["deadline"] and not entry.get("marked_blocked"):
            summary = f"Delegate worker timed out after {entry['timeout']}s " f"(capability={entry['capability']})"
            # Log + mark blocked (retry-able), but do NOT fire a Telegram WARNING:
            # a worker timeout is an expected, recoverable condition (the row is
            # visible in the Claude Requests queue), not an emergency. Pushing a
            # warning per timeout just spams the owner. Real executor exceptions
            # and dispatch failures still emit via _handle_done.
            logger.error("Delegate task #%s %s — marking blocked, thread continues", entry["task_id"], summary)
            _safe(mark_task_failed, entry["task_id"], summary)
            entry["marked_blocked"] = True
            stats["failed"] += 1
        still.append(entry)
    inflight[:] = still

    # 2) Claim only as many new tasks as there are free slots.
    busy = len(inflight)
    free = max(0, concurrency - busy)
    if free <= 0:
        if log_cycle:
            _safe(
                log_cycle,
                job_name="delegate_task_worker",
                items_processed=0,
                items_failed=stats["failed"],
                duration_ms=0,
                details={"note": "all slots busy with long-running tasks", "busy": busy},
            )
        return stats

    try:
        tasks = fetch_pending_delegations(limit=free)
    except Exception:
        logger.exception("delegation cycle: fetch_pending_delegations failed")
        return stats
    if not tasks and not inflight:
        return stats  # nothing to do, stay silent (no autonomy_loop_log spam)

    # 3) Submit all claimed tasks at once so they run concurrently.
    start = _now()
    active: Dict[Any, Dict[str, Any]] = {}
    for task in tasks:
        task_id = task["id"]
        capability = _parse_capability(task)
        source = task.get("delegation_source") or "mcp_client"
        channel = task.get("streaming_channel")
        timeout = capability_timeouts.get(capability, default_timeout)
        _safe(mark_task_in_progress, task_id)
        _safe_emit(task_id, "start", capability, "", source, channel)
        future = pool.submit(execute_delegated_task, task)
        active[future] = {
            "future": future,
            "task_id": task_id,
            "capability": capability,
            "source": source,
            "channel": channel,
            "timeout": timeout,
            "deadline": start + timeout,
            "marked_blocked": False,
        }
    stats["claimed"] = len(active)

    # 4) Collect finishers within a short cycle budget so the job returns
    #    promptly (keeps the 30s cadence responsive under max_instances=1).
    #    Whatever is still running rolls into ``inflight`` for next cycle —
    #    NOT marked blocked (its real per-capability deadline still applies).
    budget_deadline = start + cycle_budget_secs
    pending = dict(active)
    while pending:
        remaining = budget_deadline - _now()
        if remaining <= 0:
            break
        done, _ = _futures_wait(list(pending), timeout=remaining, return_when=FIRST_COMPLETED)
        if not done:
            break
        for fut in done:
            entry = pending.pop(fut)
            _handle_done(entry)

    for fut, entry in pending.items():
        inflight.append(entry)
        stats["carried"] += 1

    # 5) One cycle log row when there was activity.
    if log_cycle and (stats["claimed"] or stats["completed"] or stats["failed"] or stats["queued"]):
        duration_ms = int((_now() - start) * 1000)
        _safe(
            log_cycle,
            job_name="delegate_task_worker",
            items_processed=stats["completed"],
            items_failed=stats["failed"],
            duration_ms=duration_ms,
            details={
                "claimed": stats["claimed"],
                "completed": stats["completed"],
                "failed": stats["failed"],
                "queued": stats["queued"],
                "carried": stats["carried"],
                "busy_carryover": busy,
            },
        )
    if stats["claimed"] or stats["completed"] or stats["failed"] or stats["queued"]:
        logger.info(
            "delegate_task_worker: claimed=%d completed=%d failed=%d queued=%d carried=%d (busy_in=%d)",
            stats["claimed"],
            stats["completed"],
            stats["failed"],
            stats["queued"],
            stats["carried"],
            busy,
        )
    return stats
