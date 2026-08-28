"""
A.R.C.H.I.E. MCP Server - P.R.O.B.E. QA Tools

Tools for running QA test suites, viewing results, and generating reports
via Model Context Protocol.
"""

import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any

from . import register_tool
from database import _get_db_password

logger = logging.getLogger("archie_mcp.tools.qa")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": _get_db_password(),
}


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None, None


# ============================================================================
# RUN QA SUITE
# ============================================================================


async def run_qa_suite_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a P.R.O.B.E. QA test suite and return results.

    Executes all tests in the specified suite (or all active internal suites
    if no suite_id provided). Returns pass/fail summary with run_id for
    detailed follow-up.
    """
    import subprocess

    suite_id = arguments.get("suite_id")
    triggered_by = arguments.get("triggered_by", "mcp")

    def _run_in_container(sid, tby):
        """Run run_suite() inside archie_platform container where auth works."""
        script = (
            "import sys, json; sys.path.insert(0, '/app'); "
            f"from services.qa_service import run_suite; "
            f"print(json.dumps(run_suite({sid}, triggered_by='{tby}')))"
        )
        proc = subprocess.run(
            ["docker", "exec", "archie_platform", "python3", "-c", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"docker exec failed: {proc.stderr[:300]}")
        return json.loads(proc.stdout.strip())

    try:
        if suite_id:
            result = _run_in_container(suite_id, triggered_by)
            return {
                "success": result.get("success", False),
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "total": result.get("total", 0),
                "passed": result.get("passed", 0),
                "failed": result.get("failed", 0),
                "errors": result.get("errors", 0),
                "message": f"Suite run complete: {result.get('passed', 0)}/{result.get('total', 0)} passed",
            }
        else:
            # Run all active internal suites
            get_script = (
                "import sys, json; sys.path.insert(0, '/app'); "
                "from services.qa_service import get_suites; "
                "print(json.dumps(get_suites()))"
            )
            proc = subprocess.run(
                ["docker", "exec", "archie_platform", "python3", "-c", get_script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            suites = json.loads(proc.stdout.strip()) if proc.returncode == 0 else []
            internal = [s for s in suites if s.get("suite_type") == "internal"]
            if not internal:
                return {"success": False, "error": "No active internal suites found"}

            all_results = []
            total_passed = 0
            total_failed = 0
            total_errors = 0

            for suite in internal:
                result = _run_in_container(suite["id"], triggered_by)
                total_passed += result.get("passed", 0)
                total_failed += result.get("failed", 0)
                total_errors += result.get("errors", 0)
                all_results.append(
                    {
                        "suite_id": suite["id"],
                        "suite_name": suite["name"],
                        "run_id": result.get("run_id"),
                        "status": result.get("status"),
                        "passed": result.get("passed", 0),
                        "failed": result.get("failed", 0),
                    }
                )

            total = total_passed + total_failed + total_errors
            return {
                "success": True,
                "suites_run": len(all_results),
                "total": total,
                "passed": total_passed,
                "failed": total_failed,
                "errors": total_errors,
                "results": all_results,
                "message": f"All suites complete: {total_passed}/{total} passed across {len(all_results)} suites",
            }

    except Exception as e:
        logger.error(f"QA suite run failed: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="run_qa_suite",
    category="testing",
    description="Run a P.R.O.B.E. QA test suite. Executes API and page load tests defined in YAML specs, stores results in DB, alerts on failures. Pass suite_id for a specific suite, or omit to run all active internal suites. Returns pass/fail summary.",
    input_schema={
        "type": "object",
        "properties": {
            "suite_id": {
                "type": "integer",
                "description": "Specific suite ID to run. Omit to run all active internal suites.",
            },
            "triggered_by": {
                "type": "string",
                "description": "Who triggered the run (default: 'mcp'). Used for tracking.",
                "default": "mcp",
            },
        },
    },
    handler=run_qa_suite_handler,
    requires_permission="admin",
)


# ============================================================================
# GET QA RESULTS
# ============================================================================


async def get_qa_results_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get results for a specific QA test run.
    """
    import sys

    sys.path.insert(0, "/mnt/archie_brain/platform_v2")

    run_id = arguments.get("run_id")
    if not run_id:
        return {"success": False, "error": "run_id is required"}

    try:
        from services.qa_service import get_run_results

        run = get_run_results(run_id)
        if not run:
            return {"success": False, "error": f"Run {run_id} not found"}

        # Serialize datetimes
        for key in ["started_at", "completed_at"]:
            if run.get(key) and hasattr(run[key], "isoformat"):
                run[key] = run[key].isoformat()
        for r in run.get("results", []):
            if r.get("created_at") and hasattr(r["created_at"], "isoformat"):
                r["created_at"] = r["created_at"].isoformat()
            # Add viewable screenshot URL
            if r.get("screenshot_path"):
                filename = r["screenshot_path"].rsplit("/", 1)[-1]
                r["screenshot_url"] = f"http://192.168.1.200:3000/api/qa/screenshots/{filename}"

        return {"success": True, "run": run}

    except Exception as e:
        logger.error(f"Get QA results failed: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="get_qa_results",
    category="testing",
    description="Get detailed results for a P.R.O.B.E. QA test run. Returns per-test pass/fail status, response times, error messages, and assertions.",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {
                "type": "integer",
                "description": "The run ID to fetch results for.",
            },
        },
        "required": ["run_id"],
    },
    handler=get_qa_results_handler,
    requires_permission="read",
)


# ============================================================================
# LIST QA SUITES
# ============================================================================


async def list_qa_suites_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List all active QA test suites.
    """
    import sys

    sys.path.insert(0, "/mnt/archie_brain/platform_v2")

    try:
        from services.qa_service import get_suites, get_recent_runs

        suites = get_suites()
        recent_runs = get_recent_runs(limit=5)

        # Serialize datetimes
        for s in suites:
            for key in ["created_at", "updated_at"]:
                if s.get(key) and hasattr(s[key], "isoformat"):
                    s[key] = s[key].isoformat()
        for r in recent_runs:
            for key in ["started_at", "completed_at"]:
                if r.get(key) and hasattr(r[key], "isoformat"):
                    r[key] = r[key].isoformat()

        return {
            "success": True,
            "suites": suites,
            "recent_runs": recent_runs,
            "message": f"{len(suites)} active suites, {len(recent_runs)} recent runs",
        }

    except Exception as e:
        logger.error(f"List QA suites failed: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="list_qa_suites",
    category="testing",
    description="List all active P.R.O.B.E. QA test suites and recent run history. Use to see what suites are available before running them.",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=list_qa_suites_handler,
    requires_permission="read",
)
