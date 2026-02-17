"""
A.R.C.H.I.E. Self-Improvement Manager
Allows A.R.C.H.I.E. to propose, test, and deploy improvements with admin approval
"""

import os
import json
import psycopg2
from datetime import datetime
from pathlib import Path
import subprocess
import hashlib


class ImprovementManager:
    """Manages A.R.C.H.I.E.'s self-improvement proposals"""

    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": os.getenv("DB_PASSWORD", ""),
        }
        self.base_path = Path("/mnt/archie_brain")

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def list_proposals(self, status=None, limit=50):
        """List improvement proposals"""
        conn = self.get_db()
        cur = conn.cursor()

        if status:
            cur.execute(
                """
                SELECT * FROM improvement_proposals
                WHERE status = %s
                ORDER BY proposed_at DESC
                LIMIT %s
            """,
                (status, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM improvement_proposals
                ORDER BY proposed_at DESC
                LIMIT %s
            """,
                (limit,),
            )

        columns = [desc[0] for desc in cur.description]
        proposals = [dict(zip(columns, row)) for row in cur.fetchall()]

        cur.close()
        conn.close()

        return proposals

    def get_proposal(self, proposal_id):
        """Get specific proposal"""
        conn = self.get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT * FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        row = cur.fetchone()
        if row:
            columns = [desc[0] for desc in cur.description]
            proposal = dict(zip(columns, row))
        else:
            proposal = None

        cur.close()
        conn.close()

        return proposal

    def create_proposal(
        self,
        title,
        category,
        description,
        code_changes,
        rationale,
        priority="medium",
        risk_level="medium",
        auto_evaluate=True,
    ):
        """
        Create new improvement proposal

        Args:
            title: Proposal title
            category: Proposal category
            description: Detailed description
            code_changes: Code changes to implement
            rationale: Rationale for the improvement
            priority: Priority level (low, medium, high, critical)
            risk_level: Risk level (low, medium, high, critical)
            auto_evaluate: Automatically trigger team evaluation (default: True)

        Returns:
            Dictionary with proposal_id and optional discussion_id
        """
        conn = self.get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO improvement_proposals
            (title, category, description, code_changes, rationale, priority, risk_level, status, collaboration_enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                title,
                category,
                description,
                code_changes,
                rationale,
                priority,
                risk_level,
                "pending",
                auto_evaluate,
            ),
        )

        proposal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        result = {"proposal_id": proposal_id}

        # Phase 1.5: Auto-trigger team evaluation if enabled
        if auto_evaluate:
            try:
                # Import here to avoid circular dependencies
                import sys

                sys.path.insert(0, str(self.base_path))
                from ai_bridge.team_consensus_orchestrator import auto_evaluate_proposal

                print(f"🤖 Triggering automatic team evaluation for proposal #{proposal_id}...")
                discussion_id = auto_evaluate_proposal(proposal_id=proposal_id, generate_report=True, notify_admin=True)

                if discussion_id:
                    result["discussion_id"] = discussion_id
                    result["auto_evaluation"] = "success"
                    print(f"✅ Team evaluation complete (Discussion #{discussion_id})")
                else:
                    result["auto_evaluation"] = "failed"
                    print(f"⚠️ Team evaluation failed for proposal #{proposal_id}")

            except Exception as e:
                print(f"⚠️ Error during auto-evaluation: {e}")
                result["auto_evaluation"] = "error"
                result["auto_evaluation_error"] = str(e)

        return result

    def test_proposal(self, proposal_id):
        """Test a proposal (simplified version)"""
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        test_results = {
            "tests_passed": [],
            "tests_failed": [],
            "warnings": [],
            "recommendation": "",
        }

        # Basic syntax check for Python code
        if proposal["category"] in ["bug_fix", "feature", "optimization"]:
            code = proposal["code_changes"]
            try:
                compile(code, "<string>", "exec")
                test_results["tests_passed"].append("syntax_check")
            except SyntaxError as e:
                test_results["tests_failed"].append(f"syntax_error: {str(e)}")

        # Security check - look for dangerous operations
        dangerous_keywords = [
            "DROP TABLE",
            "DELETE FROM users",
            "os.system",
            "eval(",
            "exec(",
        ]
        code_upper = proposal["code_changes"].upper()
        for keyword in dangerous_keywords:
            if keyword in code_upper:
                test_results["warnings"].append(f"Potentially dangerous operation: {keyword}")

        # Determine recommendation
        if test_results["tests_failed"]:
            test_results["recommendation"] = "REJECT"
        elif test_results["warnings"]:
            test_results["recommendation"] = "APPROVE_WITH_CAUTION"
        else:
            test_results["recommendation"] = "APPROVE"

        # Update proposal
        conn = self.get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET test_results = %s, status = %s
            WHERE id = %s
        """,
            (json.dumps(test_results), "tested", proposal_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"success": True, "results": test_results}

    def approve_proposal(self, proposal_id, approved_by_user_id):
        """Approve a proposal"""
        conn = self.get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = %s, approved_at = %s, approved_by = %s
            WHERE id = %s
        """,
            ("approved", datetime.now(), approved_by_user_id, proposal_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"success": True}

    def reject_proposal(self, proposal_id, rejected_by_user_id, reason=None):
        """Reject a proposal"""
        conn = self.get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET status = %s, notes = %s
            WHERE id = %s
        """,
            ("rejected", reason, proposal_id),
        )

        # Log to memory
        cur.execute(
            """
            INSERT INTO long_term_memory (user_id, memory_type, category, content, tags)
            VALUES (%s, %s, %s, %s, %s)
        """,
            (
                rejected_by_user_id,
                "decision",
                "self_improvement",
                f"Rejected improvement proposal: {reason}",
                ["improvement", "rejected"],
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"success": True}

    def create_backup(self, proposal_id, proposal):
        """Create backup before deploying changes"""
        import shutil

        backup_dir = self.base_path / "backups" / f"proposal_{proposal_id}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Store metadata
        metadata = {
            "proposal_id": proposal_id,
            "title": proposal["title"],
            "category": proposal["category"],
            "created_at": timestamp,
            "code_changes": proposal["code_changes"],
        }

        with open(backup_dir / f"metadata_{timestamp}.json", "w") as f:
            json.dump(metadata, f, indent=2)

        # Backup affected files (extract from code_changes if possible)
        # For now, create a backup of the entire ai_bridge directory
        source_dir = self.base_path / "ai_bridge"
        if source_dir.exists():
            backup_file = backup_dir / f"ai_bridge_backup_{timestamp}.tar.gz"
            import tarfile

            with tarfile.open(backup_file, "w:gz") as tar:
                tar.add(source_dir, arcname="ai_bridge")

        # Backup platform directory
        platform_dir = self.base_path / "platform_v2"
        if platform_dir.exists():
            backup_file = backup_dir / f"platform_backup_{timestamp}.tar.gz"
            import tarfile

            with tarfile.open(backup_file, "w:gz") as tar:
                tar.add(platform_dir, arcname="platform_v2")

        return {
            "success": True,
            "backup_dir": str(backup_dir),
            "timestamp": timestamp,
            "files_backed_up": ["ai_bridge", "platform_v2"],
        }

    def deploy_proposal(self, proposal_id):
        """Deploy approved proposal with backup"""
        proposal = self.get_proposal(proposal_id)

        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        if proposal["status"] != "approved":
            return {"success": False, "error": "Proposal not approved"}

        try:
            # Step 1: Create backup
            backup_result = self.create_backup(proposal_id, proposal)
            if not backup_result["success"]:
                return {
                    "success": False,
                    "error": "Backup failed",
                    "details": backup_result,
                }

            # Step 2: Parse and apply code changes
            code_changes = proposal.get("code_changes", "")
            if not code_changes:
                return {"success": False, "error": "No code changes specified"}

            # Try to extract file path and changes from code_changes
            # Expected format: "File: /path/to/file.py\n\nCode:\n<code here>"
            deployment_log = []

            # For safety, we'll just log the deployment but not actually apply changes
            # In production, this would parse the code_changes and apply them
            deployment_log.append(f"Backup created at: {backup_result['backup_dir']}")
            deployment_log.append(f"Code changes ready to apply: {len(code_changes)} characters")
            deployment_log.append("⚠️ Manual deployment required - automatic code application disabled for safety")

            # Step 3: Mark as deployed
            conn = self.get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = %s,
                    deployed_at = %s,
                    metadata = metadata || %s::jsonb
                WHERE id = %s
            """,
                (
                    "deployed",
                    datetime.now(),
                    json.dumps(
                        {
                            "backup": backup_result,
                            "deployment_log": deployment_log,
                            "deployed_timestamp": datetime.now().isoformat(),
                        }
                    ),
                    proposal_id,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            return {
                "success": True,
                "message": "Proposal deployed with backup",
                "backup": backup_result,
                "deployment_log": deployment_log,
            }

        except Exception as e:
            return {"success": False, "error": f"Deployment failed: {str(e)}"}

    def get_stats(self):
        """Get improvement statistics"""
        conn = self.get_db()
        cur = conn.cursor()

        # Count both legacy (proposed, pending_approval) and modern (pending, approved) statuses
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('pending', 'proposed') THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status IN ('approved', 'pending_approval') THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status = 'tested' THEN 1 ELSE 0 END) as tested,
                SUM(CASE WHEN status IN ('deployed', 'completed') THEN 1 ELSE 0 END) as deployed,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
            FROM improvement_proposals
        """
        )

        row = cur.fetchone()
        stats = {
            "total": row[0],
            "pending": row[1],
            "approved": row[2],
            "tested": row[3],
            "deployed": row[4],
            "rejected": row[5],
        }

        cur.close()
        conn.close()

        return stats
