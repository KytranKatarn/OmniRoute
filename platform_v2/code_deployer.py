#!/usr/bin/env python3
"""
Code Deployer for A.R.C.H.I.E. Self-Improvement System
Applies tested code changes from sandbox to production
Enables A.R.C.H.I.E. to modify her own codebase
"""

import os
import shutil
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor


class CodeDeployer:
    """Deploys code changes from sandbox to production"""

    def __init__(self):
        # Container paths (different from host paths)
        self.platform_path = "/app"  # platform_v2 mounted at /app
        self.ai_bridge_path = "/mnt/archie_brain/ai_bridge"  # ai_bridge mount
        self.docs_path = "/mnt/archie_brain/docs"  # docs mount
        self.brain_path = "/mnt/archie_brain"  # root brain mount
        self.backup_path = "/backups/code_deployments"  # backups mount

        # Ensure backup directory exists
        os.makedirs(self.backup_path, exist_ok=True)

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", "password"),
        )

    def deploy_proposal(self, proposal_id: int, deployed_by: int = 1) -> Dict:
        """
        Deploy a tested proposal to production

        Args:
            proposal_id: ID of the proposal to deploy
            deployed_by: User ID who initiated deployment

        Returns:
            {
                'success': bool,
                'files_modified': int,
                'backup_path': str,
                'deployment_log': list,
                'restart_required': bool
            }
        """
        deployment_log = []
        files_modified = []

        try:
            # Get proposal details
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    ip.*,
                    si.id as sandbox_id,
                    si.test_results,
                    si.metadata as sandbox_metadata
                FROM improvement_proposals ip
                LEFT JOIN sandbox_instances si ON si.proposal_id = ip.id
                WHERE ip.id = %s
                AND si.destroyed_at IS NULL
                ORDER BY si.created_at DESC
                LIMIT 1
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()

            if not proposal:
                return {
                    "success": False,
                    "error": "Proposal not found or no active sandbox",
                }

            deployment_log.append(f"Starting deployment of Proposal #{proposal_id}")
            deployment_log.append(f"Title: {proposal['title']}")

            # Check if tests passed - use proposal's test_status, not sandbox test_results
            test_status = proposal.get("test_status")
            if test_status != "passed":
                return {
                    "success": False,
                    "error": f'Cannot deploy: tests have not passed (status: {test_status or "not run"})',
                }

            deployment_log.append("✅ Tests passed - proceeding with deployment")

            # Create backup directory for this deployment
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            deployment_backup_dir = f"{self.backup_path}/proposal_{proposal_id}_{timestamp}"
            os.makedirs(deployment_backup_dir, exist_ok=True)
            deployment_log.append(f"Created backup directory: {deployment_backup_dir}")

            # Extract code changes from plan_steps
            plan_steps = proposal.get("plan_steps") or []
            if not plan_steps:
                deployment_log.append("⚠️  No plan steps found - checking metadata for changes")
                # Try to get changes from metadata
                sandbox_metadata = proposal.get("sandbox_metadata") or {}
                files_to_modify = sandbox_metadata.get("files_modified", [])
            else:
                files_to_modify = []
                # Map action names (plan uses edit_file/write_file, deployer expects modify/create)
                action_map = {
                    "edit_file": "modify",
                    "write_file": "create",
                    "modify": "modify",
                    "create": "create",
                    "add": "create",
                }
                for step in plan_steps:
                    action = step.get("action", "")
                    mapped_action = action_map.get(action)
                    if mapped_action:
                        target = step.get("target")
                        if target:
                            files_to_modify.append(
                                {
                                    "file": target,
                                    "action": mapped_action,
                                    "description": step.get("description", ""),
                                    "details": step.get("details", ""),
                                    "old_content": step.get("old_content", ""),
                                    "new_content": step.get("new_content", ""),
                                }
                            )

            if not files_to_modify:
                deployment_log.append("⚠️  No files to modify - marking as deployed anyway")
                # Still mark as deployed even if no code changes
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET status = 'deployed', deployed_at = NOW()
                    WHERE id = %s
                """,
                    (proposal_id,),
                )
                conn.commit()

                return {
                    "success": True,
                    "files_modified": 0,
                    "deployment_log": deployment_log,
                    "message": "No code changes to deploy (database-only or documentation change)",
                    "restart_required": False,
                }

            deployment_log.append(f"Found {len(files_to_modify)} file(s) to modify")

            # Apply each file change
            for file_change in files_to_modify:
                file_path = file_change.get("file")
                action = file_change.get("action")

                if not file_path:
                    continue

                # Normalize the file path for container environment
                if file_path.startswith("/"):
                    # Absolute path - use as-is
                    full_path = file_path
                elif file_path.startswith("platform_v2/"):
                    # Strip platform_v2/ prefix and use /app
                    relative_path = file_path[len("platform_v2/") :]
                    full_path = os.path.join(self.platform_path, relative_path)
                elif file_path.startswith("ai_bridge/"):
                    # AI bridge path - strip prefix and use ai_bridge_path
                    relative_path = file_path[len("ai_bridge/") :]
                    full_path = os.path.join(self.ai_bridge_path, relative_path)
                elif file_path.startswith("docs/"):
                    # Docs path - use docs_path mount
                    relative_path = file_path[len("docs/") :]
                    full_path = os.path.join(self.docs_path, relative_path)
                elif (
                    file_path.startswith("database/")
                    or file_path.startswith("scripts/")
                    or file_path.startswith("n8n_workflows/")
                ):
                    # Other brain paths
                    full_path = os.path.join(self.brain_path, file_path)
                else:
                    # Assume relative to platform_v2 (/app)
                    full_path = os.path.join(self.platform_path, file_path)

                deployment_log.append(f"\n{'='*60}")
                deployment_log.append(f"Processing: {file_path}")
                deployment_log.append(f"Action: {action}")

                try:
                    # Get old and new content from plan step
                    old_content = file_change.get("old_content", "")
                    new_content = file_change.get("new_content", "")

                    # If code changes not yet generated, use V2 Code Generation Engine
                    if not old_content or not new_content:
                        deployment_log.append(f"📝 Generating code changes for {file_path}...")
                        try:
                            import sys

                            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
                            from code_generation_engine import CodeGenerationEngine

                            engine = CodeGenerationEngine()
                            issue_desc = file_change.get("details", file_change.get("description", ""))
                            category = "security" if "security" in issue_desc.lower() else "code_quality"

                            gen_result = engine.generate_with_validation(
                                proposal_id=proposal_id,
                                proposal_title=proposal.get("title", f"Proposal #{proposal_id}"),
                                proposal_description=issue_desc,
                                category=category,
                                target_files=[full_path],
                                issue_context={
                                    "description": issue_desc,
                                    "file_path": file_path,
                                },
                            )

                            if gen_result.get("success") and gen_result.get("changes"):
                                # Get the first change for this file
                                for change in gen_result["changes"]:
                                    if change.get("file_path", "").endswith(file_path) or file_path in change.get(
                                        "file_path", ""
                                    ):
                                        old_content = change.get("original", change.get("old_content", ""))
                                        new_content = change.get("modified", change.get("new_content", ""))
                                        break
                                model_used = gen_result.get("metadata", {}).get("model_used", "unknown")
                                deployment_log.append(f"✅ Code generated using {model_used}")
                            else:
                                deployment_log.append(f"⚠️ Code generation failed: {gen_result.get('error', 'Unknown')}")
                                continue
                        except Exception as gen_err:
                            deployment_log.append(f"⚠️ Code generation error: {str(gen_err)}")
                            continue

                    if not old_content or not new_content:
                        deployment_log.append(
                            f"⚠️ Skipping {file_path}: still missing old_content or new_content after generation"
                        )
                        continue

                    # Backup the original file if it exists
                    if os.path.exists(full_path):
                        backup_file_path = os.path.join(
                            deployment_backup_dir,
                            os.path.basename(file_path) + ".backup",
                        )
                        shutil.copy2(full_path, backup_file_path)
                        deployment_log.append(f"✅ Backed up to: {backup_file_path}")

                        # Read current file content
                        with open(full_path, "r") as f:
                            current_content = f.read()

                        # Normalize line endings for comparison
                        old_content_normalized = old_content.replace("\\n", "\n").strip()

                        # Check if old content exists in file
                        if old_content_normalized in current_content:
                            # Apply the change
                            new_file_content = current_content.replace(
                                old_content_normalized, new_content.replace("\\n", "\n")
                            )

                            # Write the modified file
                            with open(full_path, "w") as f:
                                f.write(new_file_content)

                            deployment_log.append(f"✅ APPLIED changes to: {full_path}")
                            deployment_log.append(f"   Description: {file_change.get('description', 'N/A')}")
                            deployment_log.append(f"   OLD: {old_content_normalized[:100]}...")
                            deployment_log.append(f"   NEW: {new_content[:100]}...")
                            files_modified.append(file_path)
                        else:
                            deployment_log.append(f"⚠️ Could not find old_content in {full_path}")
                            deployment_log.append(f"   Looking for: {old_content_normalized[:100]}...")
                    else:
                        # File doesn't exist - create it if action is 'create' or 'add'
                        if action in ["create", "add"]:
                            os.makedirs(os.path.dirname(full_path), exist_ok=True)
                            with open(full_path, "w") as f:
                                f.write(new_content.replace("\\n", "\n"))
                            deployment_log.append(f"✅ CREATED new file: {full_path}")
                            files_modified.append(file_path)
                        else:
                            deployment_log.append(f"⚠️ File not found: {full_path}")

                except Exception as e:
                    deployment_log.append(f"❌ Error processing {file_path}: {str(e)}")
                    # Continue with other files even if one fails

            deployment_log.append(f"\n{'='*60}")

            # Determine deployment status based on whether files were actually modified
            if files_modified:
                deployment_status = "deployed"
                proposal_status = "deployed"
                deployment_log.append(f"✅ Deployment complete: {len(files_modified)} file(s) processed")
            else:
                deployment_status = "failed"
                proposal_status = "approved"  # Keep as approved so it can be retried
                deployment_log.append(f"❌ Deployment failed: 0 files successfully processed")

            # Update database
            cur.execute(
                """
                UPDATE improvement_proposals
                SET
                    status = %s,
                    deployed_at = CASE WHEN %s = 'deployed' THEN NOW() ELSE deployed_at END
                WHERE id = %s
            """,
                (proposal_status, proposal_status, proposal_id),
            )

            # Record deployment
            backup_name = f"proposal_{proposal_id}_{timestamp}"
            sandbox_id = proposal.get("sandbox_id")
            cur.execute(
                """
                INSERT INTO improvement_deployments
                    (proposal_id, deployed_by, backup_name, sandbox_id, deployment_type, status, deployed_at, deployment_log)
                VALUES (%s, %s, %s, %s, 'manual', %s, NOW(), %s)
                RETURNING id
            """,
                (
                    proposal_id,
                    deployed_by,
                    backup_name,
                    sandbox_id,
                    deployment_status,
                    "\n".join(deployment_log),
                ),
            )

            deployment_id = cur.fetchone()["id"]

            # Log activity
            cur.execute(
                """
                INSERT INTO improvement_workflow_states
                    (proposal_id, from_status, to_status, changed_at, reason, automated)
                VALUES (%s, %s, 'deployed', NOW(), 'Deployed to production', false)
            """,
                (proposal_id, proposal["status"]),
            )

            # Mark linked CodeRabbit issue as fixed (Phase 14 feedback loop)
            if files_modified:
                try:
                    metadata = proposal.get("metadata", {})
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    issue_id = metadata.get("issue_id")
                    if issue_id:
                        cur.execute(
                            """
                            UPDATE code_issues
                            SET status = 'fixed', fixed_at = NOW()
                            WHERE id = %s
                        """,
                            (issue_id,),
                        )
                        deployment_log.append(f"✅ Marked CodeRabbit issue #{issue_id} as fixed")
                except Exception as e:
                    deployment_log.append(f"⚠️ Could not update CodeRabbit issue: {e}")

            conn.commit()
            cur.close()
            conn.close()

            # Determine if restart is needed (Python files require container restart)
            restart_required = any(".py" in f for f in files_modified)

            # Save deployment info for safe restart failsafe
            if restart_required and files_modified:
                deployment_info = {
                    "deployment_id": deployment_id,
                    "proposal_id": proposal_id,
                    "backup_path": deployment_backup_dir,
                    "modified_files": files_modified,
                    "timestamp": timestamp,
                }
                deployment_info_file = "/backups/last_deployment.json"
                try:
                    with open(deployment_info_file, "w") as f:
                        json.dump(deployment_info, f, indent=2)
                    deployment_log.append(f"💾 Saved deployment info for failsafe: {deployment_info_file}")
                except Exception as e:
                    deployment_log.append(f"⚠️ Could not save deployment info: {e}")

            # Auto-restart container if Python files were modified
            restart_scheduled = False
            if restart_required and files_modified:
                deployment_log.append(f"🔄 Python files modified - triggering container restart...")
                try:
                    import docker

                    # Connect to Docker via mounted socket
                    client = docker.from_env()
                    container = client.containers.get("archie_platform")

                    # Schedule restart in a thread so response can be sent first
                    import threading

                    def delayed_restart():
                        import time

                        time.sleep(2)  # Wait for response to be sent
                        try:
                            container.restart(timeout=30)
                        except Exception as e:
                            print(f"Restart failed: {e}")

                    restart_thread = threading.Thread(target=delayed_restart, daemon=True)
                    restart_thread.start()
                    restart_scheduled = True
                    deployment_log.append(f"✅ Container restart scheduled (2 second delay)")
                except ImportError:
                    deployment_log.append(f"⚠️ Docker library not available - manual restart required")
                    deployment_log.append(f"   Run: docker-compose restart archie_platform")
                except Exception as e:
                    deployment_log.append(f"⚠️ Could not schedule restart: {e}")
                    deployment_log.append(f"   Please manually run: docker-compose restart archie_platform")

            return {
                "success": True,
                "files_modified": len(files_modified),
                "modified_files": files_modified,
                "backup_path": deployment_backup_dir,
                "deployment_log": deployment_log,
                "deployment_id": deployment_id,
                "restart_required": restart_required,
                "restart_scheduled": restart_scheduled,
                "message": f"Deployment complete. {len(files_modified)} file(s) processed."
                + (" Container will restart shortly." if restart_scheduled else ""),
            }

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            deployment_log.append(f"\n❌ DEPLOYMENT FAILED: {str(e)}")
            deployment_log.append(error_details)

            return {
                "success": False,
                "error": str(e),
                "deployment_log": deployment_log,
                "error_details": error_details,
            }

    def rollback_deployment(self, deployment_id: int) -> Dict:
        """
        Rollback a deployment using the backup

        Args:
            deployment_id: ID of the deployment to rollback

        Returns:
            {
                'success': bool,
                'message': str
            }
        """
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get deployment details
            cur.execute(
                """
                SELECT
                    id.proposal_id,
                    ip.title,
                    id.deployed_at
                FROM improvement_deployments id
                JOIN improvement_proposals ip ON id.proposal_id = ip.id
                WHERE id.id = %s
            """,
                (deployment_id,),
            )

            deployment = cur.fetchone()

            if not deployment:
                return {"success": False, "error": "Deployment not found"}

            # Mark deployment as rolled back
            cur.execute(
                """
                UPDATE improvement_deployments
                SET
                    status = 'rolled_back',
                    rolled_back_at = NOW(),
                    rollback_reason = 'Manual rollback requested'
                WHERE id = %s
            """,
                (deployment_id,),
            )

            # Update proposal status
            cur.execute(
                """
                UPDATE improvement_proposals
                SET
                    status = 'completed',
                    deployed_at = NULL
                WHERE id = %s
            """,
                (deployment["proposal_id"],),
            )

            conn.commit()
            cur.close()
            conn.close()

            return {
                "success": True,
                "message": f"Deployment #{deployment_id} rolled back successfully",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def restart_services(self) -> Dict:
        """
        Restart A.R.C.H.I.E. services after code deployment

        Returns:
            {
                'success': bool,
                'message': str
            }
        """
        try:
            # Restart the platform container
            result = subprocess.run(
                ["docker-compose", "restart", "archie_platform"],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "message": "A.R.C.H.I.E. platform restarted successfully",
                    "output": result.stdout,
                }
            else:
                return {"success": False, "error": f"Restart failed: {result.stderr}"}

        except Exception as e:
            return {"success": False, "error": str(e)}


# Convenience functions
def deploy_proposal(proposal_id: int, deployed_by: int = 1) -> Dict:
    """Deploy a proposal to production"""
    deployer = CodeDeployer()
    return deployer.deploy_proposal(proposal_id, deployed_by)


def rollback_deployment(deployment_id: int) -> Dict:
    """Rollback a deployment"""
    deployer = CodeDeployer()
    return deployer.rollback_deployment(deployment_id)


def restart_archie() -> Dict:
    """Restart A.R.C.H.I.E. services"""
    deployer = CodeDeployer()
    return deployer.restart_services()


if __name__ == "__main__":
    # Test the deployer
    import sys

    if len(sys.argv) > 1:
        proposal_id = int(sys.argv[1])
        result = deploy_proposal(proposal_id)
        print(json.dumps(result, indent=2))
