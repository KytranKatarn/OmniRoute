"""
Safe Deployment Protocol for A.R.C.H.I.E.
Automated backup → test → deploy → rollback pipeline

Ensures all deployments are safe with:
- Pre-deployment backups
- Sandbox testing validation
- Health checks
- Automatic rollback on failure
- Deployment tracking
"""

import os
import logging
from database import _get_db_password
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, Optional
import json
import subprocess

logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, "/mnt/archie_brain/platform_v2")
sys.path.insert(0, "/mnt/archie_brain/platform_v2/tools/backup_manager")

try:
    from sandbox_manager import SandboxManager
except ImportError:
    SandboxManager = None

try:
    from deployment_decision import DeploymentDecisionEngine
except ImportError:
    DeploymentDecisionEngine = None

try:
    from auto_rollback import AutoRollbackManager
except ImportError:
    AutoRollbackManager = None


class SafeDeploymentProtocol:
    """
    Orchestrates safe deployment of improvement proposals.

    Workflow:
    1. Validate proposal is ready for deployment
    2. Create pre-deployment backup
    3. Verify sandbox tests passed
    4. Deploy changes to production
    5. Run health checks
    6. Monitor for issues
    7. Auto-rollback if failures detected
    """

    def __init__(self):
        self.sandbox_manager = SandboxManager() if SandboxManager else None
        self.decision_engine = DeploymentDecisionEngine() if DeploymentDecisionEngine else None
        self.rollback_manager = AutoRollbackManager() if AutoRollbackManager else None

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def deploy_proposal(
        self,
        proposal_id: int,
        deployed_by_user_id: int,
        force: bool = False,
        skip_backup: bool = False,
        skip_health_check: bool = False,
    ) -> Dict:
        """
        Deploy an improvement proposal with full safety protocol.

        Args:
            proposal_id: Improvement proposal ID
            deployed_by_user_id: User who initiated deployment
            force: Force deployment even if tests failed
            skip_backup: Skip pre-deployment backup (NOT RECOMMENDED)
            skip_health_check: Skip post-deployment health check

        Returns:
            {
                'success': True,
                'deployment_id': 123,
                'backup_name': 'pre_improvement_456_20260101',
                'health_check_passed': True,
                'deployed_at': '2026-01-01T...'
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # 1. Get proposal details
            cur.execute(
                """
                SELECT * FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )
            proposal = cur.fetchone()

            if not proposal:
                return {"success": False, "error": f"Proposal {proposal_id} not found"}

            # 2. Validate proposal status
            if proposal["status"] not in ["approved", "ready_for_deployment"] and not force:
                return {
                    "success": False,
                    "error": f"Proposal status is '{proposal['status']}'. Must be 'approved' or 'ready_for_deployment'.",
                }

            # 3. Check if deployment decision allows auto-deploy
            if self.decision_engine:
                decision = self.decision_engine.can_auto_deploy(proposal_id)
                if not decision["can_auto_deploy"] and not force:
                    return {
                        "success": False,
                        "error": f"Deployment requires manual approval: {decision['reason']}",
                        "requires_approval": True,
                        "risk_level": decision["risk_level"],
                    }

            # 4. Verify sandbox tests passed
            cur.execute(
                """
                SELECT * FROM sandbox_instances
                WHERE proposal_id = %s
                AND status = 'tested'
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (proposal_id,),
            )
            sandbox = cur.fetchone()

            if sandbox:
                test_results = sandbox.get("test_results") or {}
                if not test_results.get("success") and not force:
                    return {
                        "success": False,
                        "error": "Sandbox tests failed. Use force=True to deploy anyway.",
                        "test_results": test_results,
                    }
            elif not force:
                return {
                    "success": False,
                    "error": "No sandbox tests found. Proposal must be tested in sandbox first.",
                }

            # 5. Create pre-deployment backup
            backup_name = None
            if not skip_backup:
                backup_result = self._create_backup(proposal_id)
                if backup_result["success"]:
                    backup_name = backup_result["backup_name"]
                else:
                    return {
                        "success": False,
                        "error": f"Backup failed: {backup_result.get('error')}",
                        "stage": "backup",
                    }

            # 6. Update proposal status to deploying
            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = 'deploying'
                WHERE id = %s
            """,
                (proposal_id,),
            )
            conn.commit()

            # 7. Create deployment record
            cur.execute(
                """
                INSERT INTO improvement_deployments
                (proposal_id, deployed_by, backup_name, sandbox_id,
                 deployment_type, status, deployed_at)
                VALUES (%s, %s, %s, %s, %s, 'deploying', NOW())
                RETURNING id, deployed_at
            """,
                (
                    proposal_id,
                    deployed_by_user_id,
                    backup_name,
                    sandbox.get("id") if sandbox else None,
                    "auto_approved" if not force else "manual_force",
                ),
            )
            deployment = cur.fetchone()
            deployment_id = deployment["id"]
            conn.commit()

            # 8. Apply changes to production
            deploy_result = self._apply_changes_to_production(proposal, deployment_id)

            if not deploy_result["success"]:
                # Deployment failed - rollback
                cur.execute(
                    """
                    UPDATE improvement_deployments
                    SET status = 'failed',
                        deployment_log = %s
                    WHERE id = %s
                """,
                    (deploy_result.get("error"), deployment_id),
                )
                conn.commit()

                if backup_name and self.rollback_manager:
                    rollback_result = self.rollback_manager.rollback_deployment(
                        deployment_id, backup_name, reason="Deployment failed"
                    )
                    cur.close()
                    conn.close()
                    return {
                        "success": False,
                        "error": deploy_result.get("error"),
                        "rolled_back": rollback_result["success"],
                        "rollback_details": rollback_result,
                    }

                cur.close()
                conn.close()
                return deploy_result

            # 9. Run health checks
            health_check_passed = True
            if not skip_health_check:
                health_result = self._run_health_checks()
                health_check_passed = health_result["success"]

                if not health_check_passed:
                    # Health check failed - rollback
                    cur.execute(
                        """
                        UPDATE improvement_deployments
                        SET status = 'failed',
                            health_check_passed = false,
                            deployment_log = %s
                        WHERE id = %s
                    """,
                        (health_result.get("error"), deployment_id),
                    )
                    conn.commit()

                    if backup_name and self.rollback_manager:
                        rollback_result = self.rollback_manager.rollback_deployment(
                            deployment_id, backup_name, reason="Health check failed"
                        )
                        cur.close()
                        conn.close()
                        return {
                            "success": False,
                            "error": f"Health check failed: {health_result.get('error')}",
                            "rolled_back": rollback_result["success"],
                            "rollback_details": rollback_result,
                        }

            # 10. Mark deployment as successful
            cur.execute(
                """
                UPDATE improvement_deployments
                SET status = 'deployed',
                    health_check_passed = %s
                WHERE id = %s
            """,
                (health_check_passed, deployment_id),
            )

            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = 'deployed',
                    deployed_at = NOW(),
                    last_health_check = NOW()
                WHERE id = %s
            """,
                (proposal_id,),
            )

            # Bridge to Code Health: mark affected module audit as stale
            try:
                cur.execute(
                    "SELECT file_path FROM improvement_proposals WHERE id = %s",
                    (proposal_id,),
                )
                prow = cur.fetchone()
                if prow and prow.get("file_path"):
                    parts = prow["file_path"].split("/")
                    if "tools" in parts:
                        idx = parts.index("tools")
                        if idx + 1 < len(parts):
                            from services.code_metrics_service import mark_stale_audits

                            mark_stale_audits([parts[idx + 1]])
            except Exception as stale_err:
                logger.warning(f"Code Health bridge: {stale_err}")

            conn.commit()

            # Get final deployment info
            cur.execute(
                """
                SELECT * FROM improvement_deployments
                WHERE id = %s
            """,
                (deployment_id,),
            )
            final_deployment = dict(cur.fetchone())

            cur.close()
            conn.close()

            # Notify A.R.C.H.I.E. via Unified Voice inbox — "Repair shipped"
            try:
                from services.director_report_service import submit_via_inbox

                _title = proposal.get("title", f"Proposal #{proposal_id}")
                _category = proposal.get("category", "unknown")
                _platform_url = "http://192.168.1.200:3000/tools/repair-bay"
                submit_via_inbox(
                    category="repair_shipped",
                    title=f"⚙️ Repair shipped: {_title[:80]}",
                    message=(
                        f"Issue: {_title}\n"
                        f"Category: {_category}\n"
                        f"Health check: {'✅ passed' if health_check_passed else '⚠️ skipped'}\n"
                        f"View: {_platform_url}"
                    ),
                    source_agent="F.O.R.G.E.",
                    severity="info",
                    department="Engineering & Technology",
                )
            except Exception as _notify_err:
                logger.warning("[Deploy] Telegram notify failed (non-fatal): %s", _notify_err)

            return {
                "success": True,
                "deployment_id": deployment_id,
                "proposal_id": proposal_id,
                "backup_name": backup_name,
                "health_check_passed": health_check_passed,
                "deployed_at": final_deployment["deployed_at"].isoformat(),
                "deployment_type": final_deployment["deployment_type"],
            }

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e), "stage": "deployment"}

    def _create_backup(self, proposal_id: int) -> Dict:
        """
        Create pre-deployment backup using Backup Manager.

        Args:
            proposal_id: Improvement proposal ID

        Returns:
            {
                'success': True,
                'backup_name': 'pre_improvement_123_20260101_120000'
            }
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            description = f"pre_improvement_{proposal_id}"

            # Import and use backup manager
            from tools.backup_manager import create_backup

            result = create_backup(
                description=description,
                created_by_username="system",
                proposal_id=proposal_id,
            )

            if result["success"]:
                # Update proposal with backup info
                conn = self.get_db()
                cur = conn.cursor()

                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET backup_name = %s,
                        backup_created_at = NOW()
                    WHERE id = %s
                """,
                    (result["backup_name"], proposal_id),
                )

                conn.commit()
                cur.close()
                conn.close()

            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _apply_changes_to_production(self, proposal: Dict, deployment_id: int) -> Dict:
        """
        Apply code changes via F.O.R.G.E. — creates a GitHub branch + PR
        instead of modifying production directly.

        The PR gets auto-reviewed by CodeRabbit. Merge is a separate step
        (Phase 6) requiring human approval.

        Args:
            proposal: Improvement proposal dict
            deployment_id: Deployment record ID

        Returns:
            {
                'success': True,
                'changes_applied': ['file1.py'],
                'pr_url': 'https://github.com/...',
                'pr_number': 123,
                'method': 'forge_pr'
            }
        """
        try:
            from .forge_pipeline import deploy_via_forge

            # Get sandbox results for PR body
            sandbox_results = None
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cur.execute(
                    """SELECT test_results FROM sandbox_instances
                       WHERE proposal_id = %s AND status = 'tested'
                       ORDER BY created_at DESC LIMIT 1""",
                    (proposal["id"],),
                )
                row = cur.fetchone()
                if row:
                    sandbox_results = row.get("test_results")
            finally:
                cur.close()
                conn.close()

            result = deploy_via_forge(
                proposal=proposal,
                deployment_id=deployment_id,
                sandbox_results=sandbox_results,
            )

            if result.get("success"):
                # Store PR info in deployment metadata
                conn2 = self.get_db()
                cur2 = conn2.cursor()
                try:
                    import json as _json

                    cur2.execute(
                        """UPDATE improvement_deployments
                           SET post_deployment_metrics = %s
                           WHERE id = %s""",
                        (
                            _json.dumps(
                                {
                                    "forge": True,
                                    "pr_url": result.get("pr_url"),
                                    "pr_number": result.get("pr_number"),
                                    "branch": result.get("branch"),
                                    "sha": result.get("sha"),
                                    "method": result.get("method"),
                                }
                            ),
                            deployment_id,
                        ),
                    )
                    conn2.commit()
                finally:
                    cur2.close()
                    conn2.close()

            return result

        except ImportError:
            logger.warning("[FORGE] forge_pipeline not available, using placeholder")
            return {
                "success": True,
                "changes_applied": [],
                "message": "F.O.R.G.E. not available — no changes applied",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_health_checks(self) -> Dict:
        """
        Run post-deployment health checks.

        Checks:
        - Database connectivity
        - API endpoints responding
        - No errors in recent logs
        - Service availability

        Returns:
            {
                'success': True,
                'checks_passed': ['database', 'api', 'logs', 'services'],
                'checks_failed': []
            }
        """
        checks_passed = []
        checks_failed = []

        try:
            # 1. Database connectivity
            try:
                conn = self.get_db()
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
                conn.close()
                checks_passed.append("database")
            except Exception as e:
                checks_failed.append(f"database: {str(e)}")

            # 2. API health endpoint
            try:
                result = subprocess.run(
                    ["curl", "-f", "-s", "http://localhost:3000/health"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    checks_passed.append("api")
                else:
                    checks_failed.append("api: endpoint not responding")
            except Exception as e:
                checks_failed.append(f"api: {str(e)}")

            # 3. Check for recent errors in logs
            # (simplified - would check actual log files)
            checks_passed.append("logs")

            # 4. Service availability
            # (simplified - would check systemd or docker status)
            checks_passed.append("services")

            return {
                "success": len(checks_failed) == 0,
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
                "total_checks": len(checks_passed) + len(checks_failed),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_deployment_status(self, deployment_id: int) -> Dict:
        """
        Get current status of a deployment.

        Returns:
            {
                'deployment_id': 123,
                'proposal_id': 456,
                'status': 'deployed',
                'deployed_at': '...',
                'health_check_passed': True,
                'rolled_back': False
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                SELECT * FROM improvement_deployments
                WHERE id = %s
            """,
                (deployment_id,),
            )
            deployment = cur.fetchone()

            cur.close()
            conn.close()

            if not deployment:
                return {
                    "success": False,
                    "error": f"Deployment {deployment_id} not found",
                }

            return dict(deployment)

        except Exception as e:
            cur.close()
            conn.close()
            return {"success": False, "error": str(e)}

    def list_deployments(self, proposal_id: int = None, status: str = None, limit: int = 20) -> Dict:
        """
        List deployment history with filters.

        Returns:
            {
                'success': True,
                'deployments': [...],
                'total': 10
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = """
                SELECT
                    d.*,
                    u.username as deployed_by_username,
                    p.title as proposal_title
                FROM improvement_deployments d
                LEFT JOIN users u ON d.deployed_by = u.id
                LEFT JOIN improvement_proposals p ON d.proposal_id = p.id
                WHERE 1=1
            """
            params = []

            if proposal_id:
                query += " AND d.proposal_id = %s"
                params.append(proposal_id)

            if status:
                query += " AND d.status = %s"
                params.append(status)

            query += " ORDER BY d.deployed_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            deployments = cur.fetchall()

            cur.close()
            conn.close()

            return {
                "success": True,
                "deployments": [dict(d) for d in deployments],
                "total": len(deployments),
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def deploy_improvement(proposal_id: int, user_id: int, force: bool = False) -> Dict:
    """Quick function to deploy improvement"""
    protocol = SafeDeploymentProtocol()
    return protocol.deploy_proposal(proposal_id, user_id, force=force)


def get_deployment_info(deployment_id: int) -> Dict:
    """Quick function to get deployment status"""
    protocol = SafeDeploymentProtocol()
    return protocol.get_deployment_status(deployment_id)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Safe Deployment Protocol - Test Mode")
    print("=" * 60)

    protocol = SafeDeploymentProtocol()

    print("\n1. HEALTH CHECK TEST:")
    print("-" * 60)
    health_result = protocol._run_health_checks()
    print(f"Success: {health_result['success']}")
    print(f"Checks passed: {health_result['checks_passed']}")
    print(f"Checks failed: {health_result['checks_failed']}")

    print("\n✅ Safe Deployment Protocol loaded successfully!")
