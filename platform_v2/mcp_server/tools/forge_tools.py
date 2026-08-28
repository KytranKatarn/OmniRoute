"""
F.O.R.G.E. MCP Tools — Self-healing pipeline operations via MCP.

Full-cycle Optimization & Regenerative GitHub Engine.
Exposes F.O.R.G.E. capabilities to Claude and other MCP clients.
"""

import logging
from typing import Dict, Any

from . import register_tool

logger = logging.getLogger("archie_mcp.tools.forge")


async def forge_health_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Check F.O.R.G.E. pipeline health — GitHub auth + repo access."""
    try:
        from tools.repair_bay.services.github_service import health_check

        health_data = health_check()
        try:
            from tools.repair_bay.services.dependabot_service import get_repair_queue

            queue = get_repair_queue()
            health_data["repair_queue_depth"] = queue.get("count", 0) if queue.get("success") else "error"
        except Exception:
            health_data["repair_queue_depth"] = "unavailable"
        return health_data
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_stats_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get F.O.R.G.E. pipeline statistics — PRs, reviews, proposals, self-healing."""
    try:
        from tools.repair_bay.services.github_service import list_pipeline_prs, health_check

        import psycopg2
        from psycopg2.extras import RealDictCursor
        import os
        from database import _get_db_password

        gh = health_check()
        open_prs = list_pipeline_prs("open")
        merged_prs = list_pipeline_prs("merged")

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT status, COUNT(*) as count FROM improvement_proposals GROUP BY status")
            proposals = {r["status"]: r["count"] for r in cur.fetchall()}

            cur.execute("SELECT COUNT(*) as count FROM forge_reviews")
            review_count = cur.fetchone()["count"]

            cur.execute(
                """SELECT COUNT(*) as count FROM governance_audit_log
                   WHERE event_category = 'forge_self_heal'"""
            )
            heal_actions = cur.fetchone()["count"]
        finally:
            cur.close()
            conn.close()

        stats_data = {
            "success": True,
            "github_connected": gh.get("authenticated", False),
            "open_prs": open_prs.get("count", 0),
            "merged_prs": merged_prs.get("count", 0),
            "proposals": proposals,
            "total_reviews": review_count,
            "self_heal_actions": heal_actions,
        }
        try:
            from tools.repair_bay.services.dependabot_service import get_repair_queue

            queue = get_repair_queue()
            items = queue.get("items", []) if queue.get("success") else []
            stats_data["vulnerabilities"] = {
                "total": len(items),
                "pending": sum(1 for i in items if i.get("status") == "pending"),
                "fixed": sum(1 for i in items if i.get("status") == "fixed"),
                "failed": sum(1 for i in items if i.get("status") == "failed"),
                "escalated": sum(1 for i in items if i.get("status") == "escalated"),
            }
        except Exception:
            stats_data["vulnerabilities"] = "unavailable"
        return stats_data
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_self_heal_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger a F.O.R.G.E. self-healing cycle for a proposal."""
    proposal_id = arguments.get("proposal_id")
    if not proposal_id:
        return {"success": False, "error": "proposal_id is required"}

    try:
        from tools.repair_bay.services.forge_self_heal import run_self_heal_cycle

        return run_self_heal_cycle(int(proposal_id))
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_list_prs_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """List open F.O.R.G.E. pipeline PRs on GitHub."""
    try:
        from tools.repair_bay.services.github_service import list_pipeline_prs

        state = arguments.get("state", "open")
        return list_pipeline_prs(state)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_deploy_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Deploy by merging a F.O.R.G.E. PR with pre-checks."""
    pr_number = arguments.get("pr_number")
    if not pr_number:
        return {"success": False, "error": "pr_number is required"}

    try:
        from tools.repair_bay.services.forge_pipeline import deploy_via_merge

        proposal_id = arguments.get("proposal_id")
        return deploy_via_merge(int(pr_number), proposal_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_scan_vulns_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger on-demand Dependabot poll + manifest discovery."""
    from tools.repair_bay.services.dependabot_service import (
        poll_and_ingest,
        sync_manifest_registry,
        get_repair_queue,
    )

    manifests = sync_manifest_registry()
    poll = poll_and_ingest()
    queue = get_repair_queue()

    return {
        "success": True,
        "manifests_discovered": manifests.get("count", 0),
        "new_alerts": poll.get("new_alerts", 0) if poll.get("success") else 0,
        "queue_depth": queue.get("count", 0) if queue.get("success") else 0,
        "poll_error": poll.get("error") if not poll.get("success") else None,
    }


def register_forge_tools():
    """Register all F.O.R.G.E. MCP tools."""

    register_tool(
        name="forge_health",
        category="forge",
        description="Check F.O.R.G.E. pipeline health — GitHub authentication and repo access status.",
        input_schema={"type": "object", "properties": {}},
        handler=forge_health_handler,
        requires_permission="read",
    )

    register_tool(
        name="forge_stats",
        category="forge",
        description="Get F.O.R.G.E. pipeline statistics — open/merged PRs, proposals by status, review count, self-healing action count.",
        input_schema={"type": "object", "properties": {}},
        handler=forge_stats_handler,
        requires_permission="read",
    )

    register_tool(
        name="forge_self_heal",
        category="forge",
        description="Trigger a F.O.R.G.E. self-healing cycle for a proposal. Generates AI fix, ready for sandbox testing and PR creation.",
        input_schema={
            "type": "object",
            "properties": {
                "proposal_id": {
                    "type": "integer",
                    "description": "The improvement proposal ID to auto-fix",
                },
            },
            "required": ["proposal_id"],
        },
        handler=forge_self_heal_handler,
        requires_permission="write",
    )

    register_tool(
        name="forge_list_prs",
        category="forge",
        description="List F.O.R.G.E. pipeline PRs on GitHub. Filter by state: open, closed, merged, all.",
        input_schema={
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "PR state filter (open, closed, merged, all). Default: open",
                    "default": "open",
                },
            },
        },
        handler=forge_list_prs_handler,
        requires_permission="read",
    )

    register_tool(
        name="forge_deploy",
        category="forge",
        description="Deploy by merging a F.O.R.G.E. PR. Verifies CodeRabbit approved, no conflicts, then squash-merges.",
        input_schema={
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "GitHub PR number to merge",
                },
                "proposal_id": {
                    "type": "integer",
                    "description": "Optional proposal ID to update status after merge",
                },
            },
            "required": ["pr_number"],
        },
        handler=forge_deploy_handler,
        requires_permission="write",
    )

    register_tool(
        name="forge_scan_vulns",
        category="forge",
        description="Scan for dependency vulnerabilities -- polls Dependabot, discovers manifests, reports repair queue status.",
        input_schema={"type": "object", "properties": {}},
        handler=forge_scan_vulns_handler,
        requires_permission="write",
    )

    logger.info(
        "Registered 6 F.O.R.G.E. tools: forge_health, forge_stats, forge_self_heal, forge_list_prs, forge_deploy, forge_scan_vulns"
    )

    # ── Repair Bay chat/pipeline tools ─────────────────────────────────────

    register_tool(
        name="repair_bay_status",
        category="forge",
        description=(
            "Get Repair Bay pipeline status — ready-to-deploy count, deployed today, "
            "pending approvals in dispatch queue, recent fixes. Use to answer 'what needs fixing?' or 'show repair status'."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=repair_bay_status_handler,
        requires_permission="read",
    )

    register_tool(
        name="repair_bay_run",
        category="forge",
        description=(
            "Queue all ready-to-deploy low/medium risk proposals through the F.O.R.G.E. "
            "tiered approval pipeline (sandbox gate → auto-deploy). "
            "Optionally filter by risk_level. Use for 'run self-healing', 'fix all safe issues', 'deploy batch'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "risk_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Risk levels to include: low, medium, high, critical. Default: ['low','medium']",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max proposals to queue (default 10, max 25)",
                },
            },
        },
        handler=repair_bay_run_handler,
        requires_permission="write",
    )

    register_tool(
        name="repair_bay_scan",
        category="forge",
        description=(
            "Trigger a P.R.O.B.E. diagnostic scan on a specific module or the full platform. "
            "Files proposals for any issues found. Use for 'scan [module]', 'run diagnostics', 'check [module]'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "module": {
                    "type": "string",
                    "description": "Module name to scan (e.g. repair_bay, media_studio). Omit for full platform scan.",
                },
            },
        },
        handler=repair_bay_scan_handler,
        requires_permission="write",
    )

    logger.info("Registered 3 additional Repair Bay tools: repair_bay_status, repair_bay_run, repair_bay_scan")

    register_tool(
        name="code_health",
        category="forge",
        description=(
            "Code Health loop-closer (Consciousness). action=reverify re-audits deployed fixes and "
            "reports per-finding fixed/still_open (the post-deploy confirmation step); "
            "action=orchestration shows which department owns each finding + open/deployed/fixed/still_open "
            "counts; action=scan kicks a full async codebase scan (returns job_id); action=audit audits one "
            "module (sync, pass module=) or all modules (async). Use after a deploy to confirm a fix landed "
            "or to surface still-open regressions."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["scan", "audit", "reverify", "orchestration"],
                    "description": "Which Code Health operation to run.",
                },
                "module": {
                    "type": "string",
                    "description": "Optional module name to scope audit/reverify.",
                },
            },
            "required": ["action"],
        },
        handler=code_health_handler,
        requires_permission="write",
    )

    logger.info("Registered Code Health tool: code_health")


# ── Repair Bay tool handlers ────────────────────────────────────────────────
# Defined before register_forge_tools() so they are in scope at registration.


async def repair_bay_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Return Repair Bay pipeline summary."""
    try:
        from services.proposal_service import get_deploy_ready, get_deploy_history
        from database import get_db_cursor

        ready = get_deploy_ready()
        history = get_deploy_history()

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT COUNT(*) as cnt FROM dispatch_pending_queue "
                "WHERE callback_type='deploy_approve_gate' AND status='queued'"
            )
            queued = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) as cnt FROM improvement_proposals WHERE status='deployed' "
                "AND deployed_at > NOW() - INTERVAL '24 hours'"
            )
            deployed_today = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) as cnt FROM improvement_proposals WHERE status='ready_for_review'")
            ready_count = cur.fetchone()["cnt"]

        return {
            "success": True,
            "ready_to_deploy": ready_count,
            "deploy_queue_depth": queued,
            "deployed_today": deployed_today,
            "total_deployed": history.get("total_deployed", 0),
            "proposals": [
                {
                    "id": p["id"],
                    "title": p["title"][:60],
                    "risk_level": p.get("risk_level"),
                    "priority": p.get("priority"),
                }
                for p in ready.get("proposals", [])[:5]
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def repair_bay_run_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Queue all ready proposals through tiered approval (batch self-heal)."""
    try:

        risk_filter = arguments.get("risk_filter", ["low", "medium"])
        limit = arguments.get("limit", 10)
        from services.proposal_service import get_deploy_ready, request_tiered_deploy_approval

        ready = get_deploy_ready()
        proposals = [p for p in ready.get("proposals", []) if p.get("risk_level") in risk_filter][:limit]
        results = []
        for p in proposals:
            r = request_tiered_deploy_approval(p["id"])
            results.append(
                {
                    "id": p["id"],
                    "title": p["title"][:50],
                    "approver": r.get("approver"),
                    "queue_id": r.get("queue_id"),
                    "pending": r.get("pending"),
                    "tier": r.get("tier"),
                }
            )
        queued = sum(1 for r in results if r.get("queue_id"))
        return {
            "success": True,
            "total_ready": len(ready.get("proposals", [])),
            "queued": queued,
            "skipped": len(proposals) - queued,
            "results": results,
            "message": (
                f"Queued {queued} proposals for F.O.R.G.E. review. "
                f"model_dispatch_worker will execute → sandbox gate → deploy."
            ),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def repair_bay_scan_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run P.R.O.B.E. scan on a module or full platform."""
    try:
        from services.qa_service import run_suite_for_module, MODULE_SUITE_MAP

        module = arguments.get("module", "")
        if module:
            results = run_suite_for_module(module, triggered_by="mcp_repair_bay_scan")
            passed = sum(r.get("passed", 0) for r in results)
            total = sum(r.get("total", 0) for r in results)
            suites_run = len(results)
            # A module with no registered suite executed NOTHING. `passed == total`
            # is 0 == 0 there, so the old code answered all_green=True and the
            # caller read "this module is verified" when nothing had been checked.
            # Found 2026-07-26 scanning KSO, which has no suite: the scan returned
            # {suites_run: 0, total: 0, all_green: true}.
            # None means UNKNOWN. Only False/True are claims about the code.
            no_suites = suites_run == 0
            return {
                "success": True,
                "module": module,
                "suites_run": suites_run,
                "passed": passed,
                "total": total,
                "all_green": None if no_suites else passed == total,
                "no_suites_registered": no_suites,
                "warning": (
                    (
                        f"No P.R.O.B.E. suite is registered for '{module}' — nothing was "
                        f"executed, so this is NOT a pass. Add it to MODULE_SUITE_MAP."
                    )
                    if no_suites
                    else None
                ),
                "results": [
                    {
                        "run_id": r.get("run_id"),
                        "passed": r.get("passed"),
                        "total": r.get("total"),
                        "status": r.get("status"),
                    }
                    for r in results
                ],
            }
        else:
            return {
                "success": True,
                "message": "Full platform scan triggered — check Repair Bay Diagnose tab for results.",
                "available_modules": sorted(MODULE_SUITE_MAP.keys()),
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def code_health_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Code Health: reverify | orchestration (sync) · scan | audit (scan async, single-module audit sync).

    Shares the exact module-level helpers the session routes use, so the MCP
    surface and the Consciousness UI never drift (#4262)."""
    try:
        action = (arguments.get("action") or "").strip().lower()
        module = arguments.get("module") or None

        if action == "reverify":
            from services.audit_pipeline import reverify_deployed_findings

            return {"success": True, **reverify_deployed_findings(module)}
        if action == "orchestration":
            from tools.consciousness.code_health_routes import compute_orchestration

            return compute_orchestration()
        if action == "scan":
            from tools.consciousness.code_health_routes import start_code_health_scan

            payload, _ = start_code_health_scan()
            return payload
        if action == "audit":
            from tools.consciousness.code_health_routes import run_code_health_audit

            payload, _ = run_code_health_audit(module)
            return payload
        return {
            "success": False,
            "error": f"unknown action {action!r} — use scan | audit | reverify | orchestration",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


register_forge_tools()
