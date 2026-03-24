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
        from tools.dev_pipeline.services.github_service import health_check

        return health_check()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_stats_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Get F.O.R.G.E. pipeline statistics — PRs, reviews, proposals, self-healing."""
    try:
        from tools.dev_pipeline.services.github_service import list_pipeline_prs, health_check

        import psycopg2
        from psycopg2.extras import RealDictCursor
        import os

        gh = health_check()
        open_prs = list_pipeline_prs("open")
        merged_prs = list_pipeline_prs("merged")

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD"),
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

        return {
            "success": True,
            "github_connected": gh.get("authenticated", False),
            "open_prs": open_prs.get("count", 0),
            "merged_prs": merged_prs.get("count", 0),
            "proposals": proposals,
            "total_reviews": review_count,
            "self_heal_actions": heal_actions,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_self_heal_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger a F.O.R.G.E. self-healing cycle for a proposal."""
    proposal_id = arguments.get("proposal_id")
    if not proposal_id:
        return {"success": False, "error": "proposal_id is required"}

    try:
        from tools.dev_pipeline.services.forge_self_heal import run_self_heal_cycle

        return run_self_heal_cycle(int(proposal_id))
    except Exception as e:
        return {"success": False, "error": str(e)}


async def forge_list_prs_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """List open F.O.R.G.E. pipeline PRs on GitHub."""
    try:
        from tools.dev_pipeline.services.github_service import list_pipeline_prs

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
        from tools.dev_pipeline.services.forge_pipeline import deploy_via_merge

        proposal_id = arguments.get("proposal_id")
        return deploy_via_merge(int(pr_number), proposal_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


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

    logger.info(
        "Registered 5 F.O.R.G.E. tools: forge_health, forge_stats, forge_self_heal, forge_list_prs, forge_deploy"
    )


register_forge_tools()
