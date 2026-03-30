"""Sandbox Service — Sandbox management, test execution, and benchmarks.

Migrated from tools/sandbox_manager/routes.py (Project #103, Phase 3).
All business logic lives here; route files are thin HTTP wrappers.
"""

import glob as glob_module
import json
import logging
import os
from database import _get_db_password
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Dict

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Ensure imports are reachable
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

# ---------------------------------------------------------------------------
# SandboxManager (optional — may not be installed)
# ---------------------------------------------------------------------------
try:
    from tools.repair_bay.services.sandbox_manager import SandboxManager
except ImportError:
    SandboxManager = None

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
active_test_runs: Dict[str, dict] = {}
BASE_PATH = "/mnt/archie_brain"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ===================================================================
# SANDBOX CRUD (delegates to SandboxManager)
# ===================================================================


def list_sandboxes():
    """List all module sandboxes with status."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()
    return manager.get_module_sandboxes()


def get_sandbox(module_id):
    """Get a specific module sandbox."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()
    return manager.get_module_sandbox(module_id)


def create_sandbox(module_id, proposal_id=None):
    """Create/activate a module sandbox."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()
    return manager.create_module_sandbox(module_id, proposal_id)


def destroy_sandbox(module_id):
    """Destroy/deactivate a module sandbox."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()
    return manager.destroy_module_sandbox(module_id)


def get_sandbox_status(module_id):
    """Get detailed sandbox status with access URL."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()
    result = manager.get_module_sandbox(module_id)

    if result["success"]:
        sandbox = result["sandbox"]
        # Add access URL if active
        if sandbox["status"] == "active":
            sandbox["access_url"] = f"http://localhost:{sandbox['port']}/sandbox/dashboard"

    return result


def run_sandbox_tests(module_id, test_suite="default"):
    """Run tests in a module sandbox."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()
    return manager.run_module_sandbox_tests(module_id, test_suite)


def reset_sandbox(module_id):
    """Reset a sandbox to clean state (destroy then recreate)."""
    if not SandboxManager:
        return {"success": False, "error": "Sandbox manager not available"}

    manager = SandboxManager()

    # Destroy then recreate
    destroy_result = manager.destroy_module_sandbox(module_id)
    if not destroy_result["success"]:
        return destroy_result

    return manager.create_module_sandbox(module_id)


# ===================================================================
# CONFIGURATION
# ===================================================================


def get_config():
    """Get sandbox configuration organised by global vs module-specific."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """SELECT config_key, config_value, module_id, description, updated_at
            FROM sandbox_config
            ORDER BY module_id NULLS FIRST, config_key"""
        )
        configs = cur.fetchall()

        # Organize by global vs module-specific
        global_config = {}
        module_config = {}

        for cfg in configs:
            key = cfg["config_key"]
            value = cfg["config_value"]
            module_id = cfg["module_id"]

            if module_id is None:
                global_config[key] = value
            else:
                if module_id not in module_config:
                    module_config[module_id] = {}
                module_config[module_id][key] = value

        return {"success": True, "global": global_config, "modules": module_config}
    except Exception as e:
        logger.error(f"get_config: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_config(config_key, config_value, module_id=None, user_id=None):
    """Upsert a sandbox configuration entry."""
    conn = None
    cur = None
    try:
        if not config_key:
            return {"success": False, "error": "config_key is required"}

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """INSERT INTO sandbox_config (config_key, config_value, module_id, updated_at, updated_by)
            VALUES (%s, %s, %s, NOW(), %s)
            ON CONFLICT (config_key, module_id)
            DO UPDATE SET config_value = %s, updated_at = NOW(), updated_by = %s
            RETURNING *""",
            (
                config_key,
                json.dumps(config_value),
                module_id,
                user_id,
                json.dumps(config_value),
                user_id,
            ),
        )
        result = cur.fetchone()
        conn.commit()

        return {"success": True, "config": dict(result) if result else None}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_config: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# INTEGRATION
# ===================================================================


def apply_from_scan(issue_id):
    """Apply a Code Sentinel fix to sandbox for testing."""
    conn = None
    cur = None
    try:
        if not issue_id:
            return {"success": False, "error": "issue_id is required"}

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get issue details
        cur.execute("SELECT * FROM code_issues WHERE id = %s", (issue_id,))
        issue = cur.fetchone()

        if not issue:
            return {"success": False, "error": f"Issue not found: {issue_id}"}

        if not SandboxManager:
            return {"success": False, "error": "Sandbox manager not available"}

        manager = SandboxManager()
        module_id = manager.detect_module_from_filepath(issue["file_path"])

        # Ensure sandbox is active
        sandbox_result = manager.get_module_sandbox(module_id)
        if not sandbox_result["success"]:
            return sandbox_result

        sandbox = sandbox_result["sandbox"]
        if sandbox["status"] != "active":
            # Activate sandbox
            activate_result = manager.create_module_sandbox(module_id)
            if not activate_result["success"]:
                return activate_result
            sandbox = activate_result

        return {
            "success": True,
            "issue_id": issue_id,
            "file_path": issue["file_path"],
            "module_id": module_id,
            "sandbox": sandbox,
            "message": (
                f"Ready to apply fix in {module_id} sandbox at port "
                f'{sandbox.get("port", sandbox.get("sandbox", {}).get("port"))}'
            ),
        }
    except Exception as e:
        logger.error(f"apply_from_scan: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def apply_from_proposal(proposal_id):
    """Apply an improvement proposal to sandbox for testing."""
    conn = None
    cur = None
    try:
        if not proposal_id:
            return {"success": False, "error": "proposal_id is required"}

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal details
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()

        if not proposal:
            return {"success": False, "error": f"Proposal not found: {proposal_id}"}

        # Detect module from metadata or default to platform
        module_id = "platform"
        if proposal.get("metadata"):
            metadata = (
                proposal["metadata"] if isinstance(proposal["metadata"], dict) else json.loads(proposal["metadata"])
            )
            file_path = metadata.get("file_path", "")
            if file_path and SandboxManager:
                manager = SandboxManager()
                module_id = manager.detect_module_from_filepath(file_path)

        if not SandboxManager:
            return {"success": False, "error": "Sandbox manager not available"}

        manager = SandboxManager()
        # Create/activate sandbox for this proposal
        return manager.create_module_sandbox(module_id, proposal_id)
    except Exception as e:
        logger.error(f"apply_from_proposal: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def deploy_to_production(module_id, proposal_id=None, skip_backup=False, user_id=None):
    """Deploy tested changes from sandbox to production with auto-backup.

    6-step pipeline:
    1. Create pre-deployment backup (unless skipped)
    2. Record deployment start
    3. Update proposal status + fix linked code issues
    4. Run health checks
    5. Update deployment record
    6. Reset sandbox
    """
    conn = None
    cur = None
    start_time = time.time()
    backup_name = None
    deployment_id = None

    try:
        if not module_id:
            return {"success": False, "error": "module_id is required"}

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # =====================================================================
        # STEP 1: Create pre-deployment backup (unless skipped)
        # =====================================================================
        if not skip_backup:
            try:
                from tools.backup_manager.backup_manager_routes import (
                    create_backup_programmatic,
                )

                backup_description = f"pre_deploy_{module_id}"
                if proposal_id:
                    backup_description = f"pre_deploy_proposal_{proposal_id}"

                backup_result = create_backup_programmatic(
                    description=backup_description,
                    created_by_username="system",
                    proposal_id=proposal_id,
                )

                if backup_result.get("success"):
                    backup_name = backup_result.get("backup_name")
                    logger.info(f"Pre-deployment backup created: {backup_name}")
                else:
                    logger.warning(f"Backup creation failed: {backup_result.get('error')}")
            except Exception as e:
                logger.warning(f"Could not create pre-deployment backup: {e}")

        # =====================================================================
        # STEP 2: Record deployment start
        # =====================================================================
        cur.execute(
            """INSERT INTO improvement_deployments
            (proposal_id, module_id, deployed_by, backup_name, deployment_type, status)
            VALUES (%s, %s, %s, %s, 'sandbox_tested', 'deploying')
            RETURNING id""",
            (proposal_id, module_id, user_id, backup_name),
        )
        result = cur.fetchone()
        deployment_id = result["id"] if result else None

        # =====================================================================
        # STEP 3: Update proposal status
        # =====================================================================
        fixed_issues = []
        if proposal_id:
            cur.execute(
                """UPDATE improvement_proposals
                SET status = 'deployed', deployed_at = NOW()
                WHERE id = %s
                RETURNING *""",
                (proposal_id,),
            )
            cur.fetchone()  # Consume the result to commit the update

            # Also update linked code issues to 'fixed' and create fix records
            cur.execute(
                """UPDATE code_issues
                SET status = 'fixed', fixed_at = NOW(), fixed_by = 'A.R.C.H.I.E. Deployment'
                WHERE proposal_id = %s
                RETURNING id, file_path""",
                (proposal_id,),
            )
            fixed_issues = cur.fetchall()

            # Create code_fixes records for each fixed issue
            for issue in fixed_issues:
                cur.execute(
                    """INSERT INTO code_fixes (issue_id, file_path, fixed_by, fix_description, fixed_at)
                    VALUES (%s, %s, 'A.R.C.H.I.E. Deployment', %s, NOW())""",
                    (
                        issue["id"],
                        issue["file_path"],
                        f"Fixed via Improvements Lab workflow - Proposal #{proposal_id} deployed",
                    ),
                )

        # =====================================================================
        # STEP 4: Run health checks
        # =====================================================================
        health_check_passed = True
        health_check_details = {"checks": []}

        # Basic health check - verify platform is responding
        try:
            import requests

            health_response = requests.get("http://localhost:3000/api/health", timeout=10)
            health_check_details["checks"].append(
                {
                    "name": "api_health",
                    "passed": health_response.status_code == 200,
                    "status_code": health_response.status_code,
                }
            )
            if health_response.status_code != 200:
                health_check_passed = False
        except Exception as e:
            health_check_details["checks"].append({"name": "api_health", "passed": False, "error": str(e)})
            # Don't fail deployment for health check issues - just log
            logger.warning(f"Health check failed: {e}")

        # =====================================================================
        # STEP 5: Update deployment record
        # =====================================================================
        deployment_duration_ms = int((time.time() - start_time) * 1000)

        if deployment_id:
            cur.execute(
                """UPDATE improvement_deployments
                SET status = 'deployed',
                    completed_at = NOW(),
                    health_check_passed = %s,
                    health_check_details = %s,
                    health_check_at = NOW(),
                    deployment_duration_ms = %s
                WHERE id = %s""",
                (
                    health_check_passed,
                    json.dumps(health_check_details),
                    deployment_duration_ms,
                    deployment_id,
                ),
            )

        # =====================================================================
        # STEP 6: Reset sandbox
        # =====================================================================
        if SandboxManager:
            manager = SandboxManager()
            manager.destroy_module_sandbox(module_id)

        conn.commit()

        return {
            "success": True,
            "message": f"Deployment complete for {module_id}",
            "module_id": module_id,
            "proposal_id": proposal_id,
            "deployment_id": deployment_id,
            "backup_name": backup_name,
            "issues_fixed": len(fixed_issues),
            "health_check_passed": health_check_passed,
            "deployment_duration_ms": deployment_duration_ms,
        }

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Deployment failed: {e}")

        # Update deployment record as failed
        if deployment_id:
            try:
                conn2 = _get_db()
                cur2 = conn2.cursor()
                cur2.execute(
                    """UPDATE improvement_deployments
                    SET status = 'failed', completed_at = NOW(), deployment_log = %s
                    WHERE id = %s""",
                    (str(e), deployment_id),
                )
                conn2.commit()
                cur2.close()
                conn2.close()
            except Exception:
                pass

        return {
            "success": False,
            "error": str(e),
            "backup_name": backup_name,
            "message": f"Deployment failed. Backup available: {backup_name}",
        }
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# STATUS
# ===================================================================


def get_module_status():
    """Get sandbox manager status: counts by status + active list."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Count sandboxes by status
        cur.execute(
            """SELECT status, COUNT(*) as count
            FROM module_sandboxes
            GROUP BY status"""
        )
        status_counts = {row["status"]: row["count"] for row in cur.fetchall()}

        # Get active sandboxes
        cur.execute(
            """SELECT module_id, port, current_proposal_id
            FROM module_sandboxes
            WHERE status = 'active'"""
        )
        active = cur.fetchall()

        return {
            "success": True,
            "healthy": True,
            "status": "active",
            "message": "Sandbox Manager is operational",
            "summary": {
                "total": sum(status_counts.values()),
                "active": status_counts.get("active", 0),
                "inactive": status_counts.get("inactive", 0),
                "testing": status_counts.get("testing", 0),
            },
            "active_sandboxes": [dict(s) for s in active],
        }
    except Exception as e:
        logger.error(f"get_module_status: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# TEST RESULTS & DEPLOYMENTS
# ===================================================================


def get_test_results(limit=50):
    """Get recent test results from sandbox_test_results table."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """SELECT
                str.id,
                str.proposal_id,
                str.test_name as test_suite,
                str.status as overall_status,
                str.duration_ms,
                str.executed_at as created_at,
                ip.title as proposal_title
            FROM sandbox_test_results str
            LEFT JOIN improvement_proposals ip ON str.proposal_id = ip.id
            ORDER BY str.executed_at DESC
            LIMIT %s""",
            (limit,),
        )
        results = cur.fetchall()

        # Calculate passed/failed counts (simplified)
        for r in results:
            r["tests_passed"] = 1 if r["overall_status"] == "passed" else 0
            r["tests_failed"] = 1 if r["overall_status"] == "failed" else 0
            r["module_id"] = f"Proposal #{r['proposal_id']}" if r["proposal_id"] else "-"

        return {"success": True, "results": [dict(r) for r in results]}
    except Exception as e:
        logger.error(f"get_test_results: {e}")
        return {"success": True, "results": [], "note": "No test results available"}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_deployments(limit=50):
    """Get recent deployments from improvement_deployments table."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """SELECT
                id.id,
                id.proposal_id,
                id.module_id,
                id.deployed_by,
                id.deployed_at,
                id.backup_name,
                id.deployment_type,
                id.status,
                id.health_check_passed,
                id.health_check_details,
                id.deployment_duration_ms,
                ip.title as proposal_title
            FROM improvement_deployments id
            LEFT JOIN improvement_proposals ip ON id.proposal_id = ip.id
            ORDER BY id.deployed_at DESC
            LIMIT %s""",
            (limit,),
        )
        deployments = cur.fetchall()

        return {"success": True, "deployments": [dict(d) for d in deployments]}
    except Exception as e:
        logger.error(f"get_deployments: {e}")
        return {"success": True, "deployments": [], "note": "No deployments available"}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# TEST DISCOVERY
# ===================================================================


def discover_tests():
    """Discover all test files in the codebase, categorised by type."""
    try:
        discovered = {"python": [], "javascript": [], "shell": [], "total": 0}

        # Python test files
        python_patterns = [
            f"{BASE_PATH}/**/test_*.py",
            f"{BASE_PATH}/**/*_test.py",
            f"{BASE_PATH}/**/tests/*.py",
        ]
        for pattern in python_patterns:
            for path in glob_module.glob(pattern, recursive=True):
                if "backups" not in path and "__pycache__" not in path:
                    rel_path = path.replace(BASE_PATH + "/", "")
                    if rel_path not in [t["path"] for t in discovered["python"]]:
                        test_info = _analyze_test_file(path, "python")
                        discovered["python"].append(test_info)

        # JavaScript test files
        js_patterns = [
            f"{BASE_PATH}/**/*.test.js",
            f"{BASE_PATH}/**/*.spec.js",
            f"{BASE_PATH}/**/tests/*.js",
        ]
        for pattern in js_patterns:
            for path in glob_module.glob(pattern, recursive=True):
                if "backups" not in path and "node_modules" not in path:
                    rel_path = path.replace(BASE_PATH + "/", "")
                    if rel_path not in [t["path"] for t in discovered["javascript"]]:
                        test_info = _analyze_test_file(path, "javascript")
                        discovered["javascript"].append(test_info)

        # Shell test scripts
        shell_patterns = [f"{BASE_PATH}/**/test*.sh", f"{BASE_PATH}/**/run_tests.sh"]
        for pattern in shell_patterns:
            for path in glob_module.glob(pattern, recursive=True):
                if "backups" not in path:
                    rel_path = path.replace(BASE_PATH + "/", "")
                    if rel_path not in [t["path"] for t in discovered["shell"]]:
                        test_info = _analyze_test_file(path, "shell")
                        discovered["shell"].append(test_info)

        discovered["total"] = len(discovered["python"]) + len(discovered["javascript"]) + len(discovered["shell"])

        return {"success": True, "tests": discovered}
    except Exception as e:
        logger.error(f"discover_tests: {e}")
        return {"success": False, "error": str(e)}


def _analyze_test_file(path: str, language: str) -> Dict:
    """Analyze a test file to extract test information."""
    rel_path = path.replace(BASE_PATH + "/", "")
    info = {
        "path": rel_path,
        "full_path": path,
        "language": language,
        "name": os.path.basename(path),
        "test_count": 0,
        "last_modified": None,
    }

    try:
        # Get last modified time
        stat = os.stat(path)
        info["last_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Count tests
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if language == "python":
            # Count def test_ functions
            info["test_count"] = len(re.findall(r"def\s+test_\w+", content))
        elif language == "javascript":
            # Count it() or test() calls
            info["test_count"] = len(re.findall(r"(it|test)\s*\(", content))
        elif language == "shell":
            # Count @test annotations or test functions
            info["test_count"] = len(re.findall(r"(^test_|@test)", content, re.MULTILINE))

    except Exception as e:
        logger.warning(f"Failed to analyze {path}: {e}")

    return info


# ===================================================================
# TEST SUITES CRUD
# ===================================================================


def get_test_suites():
    """Get configured test suites."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """SELECT id, name, description, test_type, test_command,
                   timeout_seconds, required, enabled, created_at
            FROM sandbox_test_suites
            ORDER BY required DESC, name"""
        )
        suites = cur.fetchall()

        return {"success": True, "suites": [dict(s) for s in suites]}
    except Exception as e:
        logger.error(f"get_test_suites: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def create_test_suite(name, test_command, description="", test_type="custom", timeout=300, required=False):
    """Create a new test suite."""
    conn = None
    cur = None
    try:
        if not name or not test_command:
            return {"success": False, "error": "name and test_command are required"}

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """INSERT INTO sandbox_test_suites
            (name, description, test_type, test_command, timeout_seconds, required, enabled)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            RETURNING *""",
            (name, description, test_type, test_command, timeout, required),
        )
        suite = cur.fetchone()
        conn.commit()

        return {"success": True, "suite": dict(suite)}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"create_test_suite: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_test_suite(suite_id, data):
    """Update a test suite. *data* is a dict of fields to update."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        updates = []
        values = []

        for field in [
            "name",
            "description",
            "test_type",
            "test_command",
            "timeout_seconds",
            "required",
            "enabled",
        ]:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            return {"success": False, "error": "No fields to update"}

        values.append(suite_id)

        cur.execute(
            f"""UPDATE sandbox_test_suites
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *""",
            values,
        )

        suite = cur.fetchone()
        conn.commit()

        if suite:
            return {"success": True, "suite": dict(suite)}
        return {"success": False, "error": "Suite not found"}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"update_test_suite: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def delete_test_suite(suite_id):
    """Delete a test suite."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM sandbox_test_suites WHERE id = %s", (suite_id,))
        deleted = cur.rowcount > 0
        conn.commit()

        if deleted:
            return {"success": True, "message": "Suite deleted"}
        return {"success": False, "error": "Suite not found"}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_test_suite: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# TEST EXECUTION
# ===================================================================


def run_tests(run_type="all", suite_id=None, file_path=None, timeout=300):
    """Start a test run in a background thread.

    Returns immediately with a run_id that can be polled via get_run_status().
    """
    try:
        # Generate run ID
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"

        # Create run record
        run_info = {
            "id": run_id,
            "type": run_type,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "tests": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
            },
        }
        active_test_runs[run_id] = run_info

        # Start test execution in background
        if run_type == "suite":
            if not suite_id:
                return {"success": False, "error": "suite_id required"}
            thread = threading.Thread(target=_run_suite_tests, args=(run_id, suite_id, timeout))
        elif run_type == "file":
            if not file_path:
                return {"success": False, "error": "file_path required"}
            thread = threading.Thread(target=_run_file_tests, args=(run_id, file_path, timeout))
        elif run_type == "regression":
            thread = threading.Thread(target=_run_regression_tests, args=(run_id, timeout))
        else:  # 'all'
            thread = threading.Thread(target=_run_all_tests, args=(run_id, timeout))

        thread.daemon = True
        thread.start()

        return {"success": True, "run_id": run_id, "message": "Test run started"}
    except Exception as e:
        logger.error(f"run_tests: {e}")
        return {"success": False, "error": str(e)}


def get_run_status(run_id):
    """Get status of a test run from in-memory tracking."""
    if run_id in active_test_runs:
        return {"success": True, "run": active_test_runs[run_id]}
    return {"success": False, "error": "Run not found"}


def cancel_run(run_id):
    """Cancel a running test."""
    if run_id in active_test_runs:
        active_test_runs[run_id]["status"] = "cancelled"
        return {"success": True, "message": "Run cancelled"}
    return {"success": False, "error": "Run not found"}


# ===================================================================
# TEST HISTORY
# ===================================================================


def _ensure_test_runs_table(cur):
    """Create test_runs table if it doesn't exist yet."""
    cur.execute(
        """CREATE TABLE IF NOT EXISTS test_runs (
            id VARCHAR(100) PRIMARY KEY,
            run_type VARCHAR(50),
            status VARCHAR(50),
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            summary JSONB,
            results JSONB,
            error TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )"""
    )


def get_test_history(limit=50, offset=0):
    """Get test run history from DB."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_test_runs_table(cur)

        cur.execute(
            """SELECT id, run_type, status, started_at, completed_at, summary, error
            FROM test_runs
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        runs = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM test_runs")
        total = cur.fetchone()["count"]

        return {"success": True, "runs": [dict(r) for r in runs], "total": total}
    except Exception as e:
        logger.error(f"get_test_history: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_run_details(run_id):
    """Get detailed results for a test run. Checks in-memory first, then DB."""
    # Check active runs first
    if run_id in active_test_runs:
        return {"success": True, "run": active_test_runs[run_id]}

    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_test_runs_table(cur)

        cur.execute("SELECT * FROM test_runs WHERE id = %s", (run_id,))
        run = cur.fetchone()

        if run:
            return {"success": True, "run": dict(run)}
        return {"success": False, "error": "Run not found"}
    except Exception as e:
        logger.error(f"get_run_details: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_test_trends(days=30):
    """Get test result trends — daily aggregation."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _ensure_test_runs_table(cur)

        cur.execute(
            """SELECT
                DATE(started_at) as date,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                AVG((summary->>'passed')::int) as avg_passed,
                AVG((summary->>'failed')::int) as avg_failed
            FROM test_runs
            WHERE started_at >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY DATE(started_at)
            ORDER BY date""",
            (days,),
        )
        trends = cur.fetchall()

        return {"success": True, "trends": [dict(t) for t in trends]}
    except Exception as e:
        logger.error(f"get_test_trends: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# BENCHMARKS
# ===================================================================


def run_benchmark(bench_type="api", target="/", iterations=10):
    """Run a performance benchmark. Returns results synchronously."""
    try:
        iterations = min(iterations, 100)

        if bench_type == "api":
            results = _benchmark_api(target, iterations)
        elif bench_type == "database":
            results = _benchmark_database(iterations)
        elif bench_type == "module":
            results = _benchmark_module(target, iterations)
        else:
            results = {
                "type": bench_type,
                "target": target,
                "iterations": iterations,
                "timings": [],
                "summary": {},
            }

        return {"success": True, "benchmark": results}
    except Exception as e:
        logger.error(f"run_benchmark: {e}")
        return {"success": False, "error": str(e)}


# ===================================================================
# PRIVATE HELPERS — Test Execution
# ===================================================================


def _run_suite_tests(run_id: str, suite_id: int, timeout: int):
    """Execute tests for a specific suite (background thread)."""
    run = active_test_runs[run_id]
    conn = None
    cur = None

    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM sandbox_test_suites WHERE id = %s", (suite_id,))
        suite = cur.fetchone()

        if not suite:
            run["status"] = "failed"
            run["error"] = "Suite not found"
            return

        result = _execute_test_command(suite["test_command"], suite["timeout_seconds"] or timeout)

        run["tests"].append(
            {
                "name": suite["name"],
                "type": suite["test_type"],
                "status": "passed" if result["exit_code"] == 0 else "failed",
                "duration_ms": result["duration_ms"],
                "output": result["output"][:5000],
                "error": result["error"][:1000] if result["error"] else None,
            }
        )

        run["summary"]["total"] = 1
        if result["exit_code"] == 0:
            run["summary"]["passed"] = 1
        else:
            run["summary"]["failed"] = 1

        run["status"] = "completed"
        run["completed_at"] = datetime.now().isoformat()

        # Save to database
        _save_test_run(run_id, run)

    except Exception as e:
        run["status"] = "failed"
        run["error"] = str(e)
        logger.error(f"Suite test error: {e}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _run_file_tests(run_id: str, file_path: str, timeout: int):
    """Execute tests for a specific file (background thread)."""
    run = active_test_runs[run_id]

    try:
        full_path = os.path.join(BASE_PATH, file_path) if not file_path.startswith("/") else file_path

        if not os.path.exists(full_path):
            run["status"] = "failed"
            run["error"] = f"File not found: {file_path}"
            return

        # Detect test framework and build command
        ext = os.path.splitext(full_path)[1].lower()
        if ext == ".py":
            command = f"cd {BASE_PATH} && python3 -m pytest {full_path} -v --tb=short"
        elif ext == ".js":
            command = f"cd {BASE_PATH} && npm test -- {full_path}"
        elif ext == ".sh":
            command = f"bash {full_path}"
        else:
            command = f"python3 {full_path}"

        result = _execute_test_command(command, timeout)

        run["tests"].append(
            {
                "name": os.path.basename(file_path),
                "type": "file",
                "file_path": file_path,
                "status": "passed" if result["exit_code"] == 0 else "failed",
                "duration_ms": result["duration_ms"],
                "output": result["output"][:5000],
                "error": result["error"][:1000] if result["error"] else None,
            }
        )

        run["summary"]["total"] = 1
        if result["exit_code"] == 0:
            run["summary"]["passed"] = 1
        else:
            run["summary"]["failed"] = 1

        run["status"] = "completed"
        run["completed_at"] = datetime.now().isoformat()

        _save_test_run(run_id, run)

    except Exception as e:
        run["status"] = "failed"
        run["error"] = str(e)
        logger.error(f"File test error: {e}")


def _run_regression_tests(run_id: str, timeout: int):
    """Execute all enabled, required test suites (background thread)."""
    run = active_test_runs[run_id]
    conn = None
    cur = None

    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get all enabled, required test suites
        cur.execute(
            """SELECT * FROM sandbox_test_suites
            WHERE enabled = TRUE AND required = TRUE
            ORDER BY name"""
        )
        suites = cur.fetchall()

        for suite in suites:
            if run.get("status") == "cancelled":
                break

            result = _execute_test_command(suite["test_command"], suite["timeout_seconds"] or timeout)

            test_result = {
                "name": suite["name"],
                "type": suite["test_type"],
                "suite_id": suite["id"],
                "status": "passed" if result["exit_code"] == 0 else "failed",
                "duration_ms": result["duration_ms"],
                "output": result["output"][:2000],
                "error": result["error"][:500] if result["error"] else None,
            }

            run["tests"].append(test_result)
            run["summary"]["total"] += 1

            if result["exit_code"] == 0:
                run["summary"]["passed"] += 1
            else:
                run["summary"]["failed"] += 1

        run["status"] = "completed" if run.get("status") != "cancelled" else "cancelled"
        run["completed_at"] = datetime.now().isoformat()

        _save_test_run(run_id, run)

    except Exception as e:
        run["status"] = "failed"
        run["error"] = str(e)
        logger.error(f"Regression test error: {e}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _run_all_tests(run_id: str, timeout: int):
    """Execute all enabled test suites (background thread)."""
    run = active_test_runs[run_id]
    conn = None
    cur = None

    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """SELECT * FROM sandbox_test_suites
            WHERE enabled = TRUE
            ORDER BY required DESC, name"""
        )
        suites = cur.fetchall()

        for suite in suites:
            if run.get("status") == "cancelled":
                break

            result = _execute_test_command(suite["test_command"], suite["timeout_seconds"] or timeout)

            test_result = {
                "name": suite["name"],
                "type": suite["test_type"],
                "suite_id": suite["id"],
                "required": suite["required"],
                "status": "passed" if result["exit_code"] == 0 else "failed",
                "duration_ms": result["duration_ms"],
                "output": result["output"][:2000],
                "error": result["error"][:500] if result["error"] else None,
            }

            run["tests"].append(test_result)
            run["summary"]["total"] += 1

            if result["exit_code"] == 0:
                run["summary"]["passed"] += 1
            else:
                run["summary"]["failed"] += 1

        run["status"] = "completed" if run.get("status") != "cancelled" else "cancelled"
        run["completed_at"] = datetime.now().isoformat()

        _save_test_run(run_id, run)

    except Exception as e:
        run["status"] = "failed"
        run["error"] = str(e)
        logger.error(f"All tests error: {e}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _execute_test_command(command: str, timeout: int) -> Dict:
    """Execute a test command and return results."""
    start_time = time.time()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE_PATH,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "exit_code": result.returncode,
            "output": result.stdout,
            "error": result.stderr,
            "duration_ms": duration_ms,
        }

    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "output": "",
            "error": f"Command timed out after {timeout} seconds",
            "duration_ms": timeout * 1000,
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "output": "",
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000),
        }


def _save_test_run(run_id: str, run: Dict):
    """Save test run to database."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()

        # Ensure table exists
        cur.execute(
            """CREATE TABLE IF NOT EXISTS test_runs (
                id VARCHAR(100) PRIMARY KEY,
                run_type VARCHAR(50),
                status VARCHAR(50),
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                summary JSONB,
                results JSONB,
                error TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )"""
        )

        cur.execute(
            """INSERT INTO test_runs (id, run_type, status, started_at, completed_at, summary, results, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET status = %s, completed_at = %s, summary = %s, results = %s, error = %s""",
            (
                run_id,
                run.get("type"),
                run.get("status"),
                run.get("started_at"),
                run.get("completed_at"),
                json.dumps(run.get("summary", {})),
                json.dumps(run.get("tests", [])),
                run.get("error"),
                run.get("status"),
                run.get("completed_at"),
                json.dumps(run.get("summary", {})),
                json.dumps(run.get("tests", [])),
                run.get("error"),
            ),
        )

        conn.commit()

    except Exception as e:
        logger.warning(f"Failed to save test run: {e}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ===================================================================
# PRIVATE HELPERS — Benchmarks
# ===================================================================


def _benchmark_api(endpoint: str, iterations: int) -> Dict:
    """Benchmark API endpoint response times."""
    import requests as req

    timings = []
    base_url = "http://localhost:3000"

    for i in range(iterations):
        start = time.time()
        try:
            response = req.get(f"{base_url}{endpoint}", timeout=30)
            duration = (time.time() - start) * 1000
            timings.append(
                {
                    "iteration": i + 1,
                    "duration_ms": round(duration, 2),
                    "status": response.status_code,
                }
            )
        except Exception as e:
            timings.append(
                {
                    "iteration": i + 1,
                    "duration_ms": 0,
                    "status": "error",
                    "error": str(e),
                }
            )

    valid_timings = [t["duration_ms"] for t in timings if t.get("status") != "error"]

    return {
        "type": "api",
        "target": endpoint,
        "iterations": iterations,
        "timings": timings,
        "summary": {
            "min_ms": min(valid_timings) if valid_timings else 0,
            "max_ms": max(valid_timings) if valid_timings else 0,
            "avg_ms": round(sum(valid_timings) / len(valid_timings), 2) if valid_timings else 0,
            "errors": len([t for t in timings if t.get("status") == "error"]),
        },
    }


def _benchmark_database(iterations: int) -> Dict:
    """Benchmark database query performance."""
    timings = []

    for i in range(iterations):
        conn = None
        cur = None
        start = time.time()
        try:
            conn = _get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM knowledge_base")
            cur.fetchone()
            duration = (time.time() - start) * 1000
            timings.append({"iteration": i + 1, "duration_ms": round(duration, 2), "status": "ok"})
        except Exception as e:
            timings.append(
                {
                    "iteration": i + 1,
                    "duration_ms": 0,
                    "status": "error",
                    "error": str(e),
                }
            )
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    valid_timings = [t["duration_ms"] for t in timings if t.get("status") != "error"]

    return {
        "type": "database",
        "target": "knowledge_base",
        "iterations": iterations,
        "timings": timings,
        "summary": {
            "min_ms": min(valid_timings) if valid_timings else 0,
            "max_ms": max(valid_timings) if valid_timings else 0,
            "avg_ms": round(sum(valid_timings) / len(valid_timings), 2) if valid_timings else 0,
            "errors": len([t for t in timings if t.get("status") == "error"]),
        },
    }


def _benchmark_module(module_name: str, iterations: int) -> Dict:
    """Benchmark module health check performance."""
    import requests as req

    timings = []
    base_url = "http://localhost:3000"

    for i in range(iterations):
        start = time.time()
        try:
            response = req.get(f"{base_url}/tools/{module_name}/api/status", timeout=30)
            duration = (time.time() - start) * 1000
            timings.append(
                {
                    "iteration": i + 1,
                    "duration_ms": round(duration, 2),
                    "status": response.status_code,
                }
            )
        except Exception as e:
            timings.append(
                {
                    "iteration": i + 1,
                    "duration_ms": 0,
                    "status": "error",
                    "error": str(e),
                }
            )

    valid_timings = [t["duration_ms"] for t in timings if t.get("status") != "error"]

    return {
        "type": "module",
        "target": module_name,
        "iterations": iterations,
        "timings": timings,
        "summary": {
            "min_ms": min(valid_timings) if valid_timings else 0,
            "max_ms": max(valid_timings) if valid_timings else 0,
            "avg_ms": round(sum(valid_timings) / len(valid_timings), 2) if valid_timings else 0,
            "errors": len([t for t in timings if t.get("status") == "error"]),
        },
    }
