"""
Auto-Rollback Manager for A.R.C.H.I.E.
Automatically reverts failed deployments to pre-deployment state

Features:
- Automatic rollback on deployment failure
- Backup restoration
- Health check validation
- Rollback tracking and audit trail
"""

import os
from database import _get_db_password
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict
import subprocess

sys.path.insert(0, "/mnt/archie_brain/platform_v2/tools/backup_manager")


class AutoRollbackManager:
    """
    Manages automatic rollback of failed deployments.

    Workflow:
    1. Detect deployment failure
    2. Locate pre-deployment backup
    3. Execute rollback script
    4. Verify restoration
    5. Update deployment record
    6. Send notifications
    """

    def __init__(self):
        self.backup_dir = "/mnt/archie_brain/backups"

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def rollback_deployment(
        self,
        deployment_id: int,
        backup_name: str = None,
        reason: str = None,
        auto_triggered: bool = True,
    ) -> Dict:
        """
        Rollback a deployment to pre-deployment state.

        Args:
            deployment_id: Deployment record ID
            backup_name: Backup to restore (auto-detected if None)
            reason: Reason for rollback
            auto_triggered: Whether rollback was triggered automatically

        Returns:
            {
                'success': True,
                'deployment_id': 123,
                'backup_restored': 'pre_improvement_456_...',
                'rolled_back_at': '2026-01-01T...'
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # 1. Get deployment details
            cur.execute(
                """
                SELECT * FROM improvement_deployments
                WHERE id = %s
            """,
                (deployment_id,),
            )
            deployment = cur.fetchone()

            if not deployment:
                return {
                    "success": False,
                    "error": f"Deployment {deployment_id} not found",
                }

            # 2. Check if already rolled back
            if deployment["status"] == "rolled_back":
                return {
                    "success": False,
                    "error": "Deployment already rolled back",
                    "rolled_back_at": deployment["rolled_back_at"],
                }

            # 3. Get backup name
            if not backup_name:
                backup_name = deployment.get("backup_name")

            if not backup_name:
                return {
                    "success": False,
                    "error": "No backup reference found. Cannot rollback.",
                }

            # 4. Verify backup exists
            backup_path = os.path.join(self.backup_dir, backup_name)
            if not os.path.exists(backup_path):
                return {"success": False, "error": f"Backup not found: {backup_path}"}

            # 5. Execute rollback
            rollback_result = self._execute_rollback(backup_name, backup_path)

            if not rollback_result["success"]:
                cur.close()
                conn.close()
                return rollback_result

            # 6. Update deployment record
            cur.execute(
                """
                UPDATE improvement_deployments
                SET status = 'rolled_back',
                    rolled_back_at = NOW(),
                    rollback_reason = %s
                WHERE id = %s
                RETURNING rolled_back_at
            """,
                (reason or "Auto-rollback triggered", deployment_id),
            )

            result = cur.fetchone()
            rolled_back_at = result["rolled_back_at"]

            # 7. Update proposal status
            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = 'deployment_failed'
                WHERE id = %s
            """,
                (deployment["proposal_id"],),
            )

            conn.commit()

            # 8. Create notification (if notifications table exists)
            try:
                cur.execute(
                    """
                    INSERT INTO notifications
                    (user_id, type, title, message, created_at)
                    VALUES (%s, 'deployment_rollback', %s, %s, NOW())
                """,
                    (
                        deployment["deployed_by"],
                        f"Deployment Rolled Back",
                        f"Deployment #{deployment_id} was rolled back. Reason: {reason}",
                    ),
                )
                conn.commit()
            except Exception:
                pass  # Notifications table might not exist

            cur.close()
            conn.close()

            return {
                "success": True,
                "deployment_id": deployment_id,
                "proposal_id": deployment["proposal_id"],
                "backup_restored": backup_name,
                "rolled_back_at": rolled_back_at.isoformat(),
                "reason": reason,
                "auto_triggered": auto_triggered,
            }

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def _execute_rollback(self, backup_name: str, backup_path: str) -> Dict:
        """
        Execute the actual rollback using backup restore script.

        Args:
            backup_name: Name of backup
            backup_path: Path to backup directory

        Returns:
            {
                'success': True,
                'components_restored': ['database', 'platform', 'ai_bridge']
            }
        """
        try:
            # Look for rollback script
            rollback_script = os.path.join(backup_path, "rollback.sh")

            if not os.path.exists(rollback_script):
                # M-7: real Backup Manager backups do NOT ship a rollback.sh, so
                # this is the common case — not an edge case — which means the
                # legacy script path silently made every auto-rollback fail.
                # Fall back to the Backup Manager's restore_components(), but ONLY
                # when explicitly enabled: restoring code over the live platform
                # is destructive and cannot be safely auto-tested here.
                if os.getenv("AUTO_ROLLBACK_RESTORE_ENABLED", "false").lower() == "true":
                    return self._restore_via_backup_manager(backup_name, backup_path)
                return {
                    "success": False,
                    "needs_manual": True,
                    "error": (
                        f"No rollback.sh in backup '{backup_name}'. Auto-restore is "
                        f"disabled (set AUTO_ROLLBACK_RESTORE_ENABLED=true to allow "
                        f"Backup Manager restore_components). Restore manually via "
                        f"/tools/backup-manager (backup at {backup_path})."
                    ),
                }

            # Make script executable
            os.chmod(rollback_script, 0o755)

            # Execute rollback script
            result = subprocess.run(
                ["bash", rollback_script],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
                cwd=backup_path,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "components_restored": self._parse_rollback_output(result.stdout),
                    "output": result.stdout,
                }
            else:
                return {
                    "success": False,
                    "error": f"Rollback script failed: {result.stderr}",
                    "output": result.stdout,
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Rollback timed out after 10 minutes"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _restore_via_backup_manager(self, backup_name: str, backup_path: str) -> Dict:
        """No-rollback.sh fallback — returns the canonical HOST restore path (#3515).

        DO NOT call restore_components(["code","config"]) here: it has no 'code'/'config'
        branches and assumes the OLD plain-dir layout, so it silently no-ops yet reports
        success — a dangerous false-positive that marks a still-broken deploy as 'rolled
        back'. Until true in-process auto-restore is built (untar Phase 1-6 code + decrypt
        config, with a sandbox test), surface the canonical host command and require manual
        action — consistent with #4049 (the platform cannot safely restore itself in-process).
        """
        try:
            from tools.backup_manager._shared import _host_restore_command

            host_cmd = _host_restore_command(backup_path, db="all", force=True)
        except Exception:
            host_cmd = f"scripts/backup/restore_db.sh {backup_path} --db all --force"
        return {
            "success": False,
            "needs_manual": True,
            "error": (
                f"Auto-restore not available for backup '{backup_name}' (no rollback.sh; "
                f"in-process restore cannot safely handle the current backup layout). Restore "
                f"manually: DB via `{host_cmd}` (runbook KB #272184); code/config via "
                f"/tools/backup-manager. Backup at {backup_path}."
            ),
            "host_command": host_cmd,
            "kb": "#272184",
        }

    def _parse_rollback_output(self, output: str) -> list:
        """
        Parse rollback script output to determine what was restored.

        Args:
            output: stdout from rollback script

        Returns:
            List of component names that were restored
        """
        components = []

        if "database" in output.lower():
            components.append("database")
        if "platform" in output.lower():
            components.append("platform")
        if "ai_bridge" in output.lower():
            components.append("ai_bridge")
        if "docs" in output.lower():
            components.append("docs")

        return components if components else ["unknown"]

    def can_rollback(self, deployment_id: int) -> Dict:
        """
        Check if a deployment can be rolled back.

        Returns:
            {
                'can_rollback': True,
                'backup_available': True,
                'backup_name': 'pre_improvement_...',
                'reason': '...'
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
                return {"can_rollback": False, "reason": "Deployment not found"}

            if deployment["status"] == "rolled_back":
                return {"can_rollback": False, "reason": "Already rolled back"}

            backup_name = deployment.get("backup_name")
            if not backup_name:
                return {
                    "can_rollback": False,
                    "backup_available": False,
                    "reason": "No backup reference",
                }

            backup_path = os.path.join(self.backup_dir, backup_name)
            backup_exists = os.path.exists(backup_path)

            if not backup_exists:
                return {
                    "can_rollback": False,
                    "backup_available": False,
                    "backup_name": backup_name,
                    "reason": "Backup not found on disk",
                }

            return {
                "can_rollback": True,
                "backup_available": True,
                "backup_name": backup_name,
                "backup_path": backup_path,
                "deployment_status": deployment["status"],
            }

        except Exception as e:
            return {"can_rollback": False, "reason": str(e)}

    def get_rollback_history(self, proposal_id: int = None, limit: int = 20) -> Dict:
        """
        Get history of rollbacks.

        Returns:
            {
                'success': True,
                'rollbacks': [...],
                'total': 5
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            query = """
                SELECT
                    d.*,
                    p.title as proposal_title,
                    u.username as deployed_by_username
                FROM improvement_deployments d
                LEFT JOIN improvement_proposals p ON d.proposal_id = p.id
                LEFT JOIN users u ON d.deployed_by = u.id
                WHERE d.status = 'rolled_back'
            """
            params = []

            if proposal_id:
                query += " AND d.proposal_id = %s"
                params.append(proposal_id)

            query += " ORDER BY d.rolled_back_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            rollbacks = cur.fetchall()

            cur.close()
            conn.close()

            return {
                "success": True,
                "rollbacks": [dict(r) for r in rollbacks],
                "total": len(rollbacks),
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def rollback_failed_deployment(deployment_id: int, reason: str = None) -> Dict:
    """Quick function to rollback deployment"""
    manager = AutoRollbackManager()
    return manager.rollback_deployment(deployment_id, reason=reason)


def check_rollback_status(deployment_id: int) -> Dict:
    """Quick function to check if deployment can be rolled back"""
    manager = AutoRollbackManager()
    return manager.can_rollback(deployment_id)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Auto-Rollback Manager - Test Mode")
    print("=" * 60)

    manager = AutoRollbackManager()

    print("\n1. BACKUP DIRECTORY CHECK:")
    print("-" * 60)
    if os.path.exists(manager.backup_dir):
        print(f"✓ Backup directory exists: {manager.backup_dir}")
        backups = os.listdir(manager.backup_dir)
        print(f"  Found {len(backups)} backups")
    else:
        print(f"✗ Backup directory not found: {manager.backup_dir}")

    print("\n✅ Auto-Rollback Manager loaded successfully!")
