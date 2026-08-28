"""
Sandbox Documentation Auto-Updater
Automatically updates documentation when sandbox deployments complete.

Features:
- Update CHANGELOG.md on successful deployments
- Update TROUBLESHOOTING.md on failures
- Update Blueprint roadmap status
- Sync with knowledge_base
"""

import os
from database import _get_db_password
import json
import logging
from datetime import datetime
from services.time_utils import now_local
from typing import Optional, Dict, Any

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
DOCS_PATH = "/mnt/archie_brain/docs"
CHANGELOG_PATH = os.path.join(DOCS_PATH, "CHANGELOG.md")
TROUBLESHOOTING_PATH = os.path.join(DOCS_PATH, "TROUBLESHOOTING.md")


def get_db():
    """Get database connection"""
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


class SandboxDocsUpdater:
    """Auto-update documentation based on sandbox outcomes"""

    def __init__(self):
        self.docs_path = DOCS_PATH
        self.changelog_path = CHANGELOG_PATH
        self.troubleshooting_path = TROUBLESHOOTING_PATH

    def on_deployment_success(
        self,
        proposal_id: int,
        module_id: str,
        title: str,
        description: str,
        category: str,
    ) -> Dict[str, Any]:
        """
        Called when a sandbox deployment succeeds.
        Updates CHANGELOG.md and Blueprint status.

        Args:
            proposal_id: The improvement proposal ID
            module_id: Module that was updated
            title: Proposal title
            description: Brief description
            category: Category (feature, bugfix, etc.)

        Returns:
            Result dict with updated files
        """
        results = {
            "changelog_updated": False,
            "blueprint_updated": False,
            "knowledge_updated": False,
            "errors": [],
        }

        # 1. Update CHANGELOG.md
        try:
            self._update_changelog(
                proposal_id=proposal_id,
                module_id=module_id,
                title=title,
                category=category,
            )
            results["changelog_updated"] = True
            logger.info(f"Updated CHANGELOG.md for proposal #{proposal_id}")
        except Exception as e:
            results["errors"].append(f"CHANGELOG: {str(e)}")
            logger.error(f"Failed to update CHANGELOG: {e}")

        # 2. Update Blueprint roadmap
        try:
            self._update_blueprint_task(proposal_id, "completed", module_id)
            results["blueprint_updated"] = True
            logger.info(f"Updated Blueprint for proposal #{proposal_id}")
        except Exception as e:
            results["errors"].append(f"Blueprint: {str(e)}")
            logger.error(f"Failed to update Blueprint: {e}")

        # 3. Record in knowledge_base
        try:
            self._record_deployment_knowledge(proposal_id=proposal_id, module_id=module_id, title=title, success=True)
            results["knowledge_updated"] = True
        except Exception as e:
            results["errors"].append(f"Knowledge: {str(e)}")

        results["success"] = len(results["errors"]) == 0
        return results

    def on_deployment_failure(
        self,
        proposal_id: int,
        module_id: str,
        title: str,
        error_message: str,
        error_details: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Called when a sandbox deployment fails.
        Updates TROUBLESHOOTING.md and records mistake_learned.

        Args:
            proposal_id: The improvement proposal ID
            module_id: Module that failed
            title: Proposal title
            error_message: The error that occurred
            error_details: Additional error details

        Returns:
            Result dict with updated files
        """
        results = {
            "troubleshooting_updated": False,
            "blueprint_updated": False,
            "mistake_recorded": False,
            "errors": [],
        }

        # 1. Update TROUBLESHOOTING.md
        try:
            self._update_troubleshooting(
                proposal_id=proposal_id,
                module_id=module_id,
                title=title,
                error_message=error_message,
                error_details=error_details,
            )
            results["troubleshooting_updated"] = True
            logger.info(f"Updated TROUBLESHOOTING.md for proposal #{proposal_id}")
        except Exception as e:
            results["errors"].append(f"TROUBLESHOOTING: {str(e)}")
            logger.error(f"Failed to update TROUBLESHOOTING: {e}")

        # 2. Update Blueprint roadmap as failed
        try:
            self._update_blueprint_task(proposal_id, "failed", module_id)
            results["blueprint_updated"] = True
        except Exception as e:
            results["errors"].append(f"Blueprint: {str(e)}")

        # 3. Record mistake_learned
        try:
            self._record_deployment_knowledge(
                proposal_id=proposal_id,
                module_id=module_id,
                title=title,
                success=False,
                error_message=error_message,
            )
            results["mistake_recorded"] = True
        except Exception as e:
            results["errors"].append(f"Mistake: {str(e)}")

        results["success"] = len(results["errors"]) == 0
        return results

    def _update_changelog(self, proposal_id: int, module_id: str, title: str, category: str):
        """Add entry to CHANGELOG.md"""
        if not os.path.exists(self.changelog_path):
            logger.warning(f"CHANGELOG.md not found at {self.changelog_path}")
            return

        # Read current changelog
        with open(self.changelog_path, "r") as f:
            content = f.read()

        # Create entry
        today = now_local().strftime("%Y-%m-%d")
        category_emoji = {
            "feature": "Added",
            "bugfix": "Fixed",
            "bug_fix": "Fixed",
            "security": "Security",
            "performance": "Changed",
            "code_quality": "Changed",
            "refactor": "Changed",
        }.get(category, "Changed")

        entry = f"- [{category_emoji}] {title} (#{proposal_id}) - {module_id}"

        # Find where to insert (after first ## heading)
        lines = content.split("\n")
        insert_index = 0

        for i, line in enumerate(lines):
            if line.startswith("## "):
                # Check if this is today's date section
                if today in line:
                    insert_index = i + 1
                    break
                else:
                    # Insert a new date section
                    new_section = f"\n## [{today}]\n\n{entry}\n"
                    lines.insert(i, new_section)
                    insert_index = -1  # Mark as already inserted
                    break

        if insert_index > 0:
            # Insert into existing section
            lines.insert(insert_index, entry)

        # Write back
        with open(self.changelog_path, "w") as f:
            f.write("\n".join(lines))

    def _update_troubleshooting(
        self,
        proposal_id: int,
        module_id: str,
        title: str,
        error_message: str,
        error_details: Optional[str] = None,
    ):
        """Add entry to TROUBLESHOOTING.md"""
        if not os.path.exists(self.troubleshooting_path):
            logger.warning(f"TROUBLESHOOTING.md not found at {self.troubleshooting_path}")
            return

        # Read current content
        with open(self.troubleshooting_path, "r") as f:
            content = f.read()

        # Create entry
        today = now_local().strftime("%Y-%m-%d")
        entry = f"""
### Sandbox Deployment Failed - {module_id} (#{proposal_id})
**Date:** {today}
**Proposal:** {title}

**Error:**
```
{error_message}
```

{f'**Details:** {error_details}' if error_details else ''}

**Status:** Under investigation

---
"""

        # Find the "## Recent Issues" section or add at top
        if "## Recent Issues" in content:
            content = content.replace("## Recent Issues", f"## Recent Issues\n{entry}")
        else:
            # Add section at the top (after title)
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("# "):
                    lines.insert(i + 1, f"\n## Recent Issues\n{entry}")
                    break
            content = "\n".join(lines)

        # Write back
        with open(self.troubleshooting_path, "w") as f:
            f.write(content)

    def _update_blueprint_task(self, proposal_id: int, status: str, module_id: str):
        """Update Blueprint roadmap database"""
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if there's a roadmap task linked to this proposal
            cur.execute(
                """
                SELECT id FROM roadmap_tasks
                WHERE metadata->>'proposal_id' = %s
            """,
                (str(proposal_id),),
            )

            task = cur.fetchone()

            if task:
                # Update existing task
                cur.execute(
                    """
                    UPDATE roadmap_tasks
                    SET status = %s,
                        completed_at = CASE WHEN %s = 'completed' THEN NOW() ELSE NULL END,
                        updated_at = NOW()
                    WHERE id = %s
                """,
                    (status, status, task["id"]),
                )
            else:
                # Get proposal details and create task
                cur.execute(
                    """
                    SELECT title, category, priority
                    FROM improvement_proposals
                    WHERE id = %s
                """,
                    (proposal_id,),
                )
                proposal = cur.fetchone()

                if proposal:
                    cur.execute(
                        """
                        INSERT INTO roadmap_tasks
                        (title, description, status, category, priority, module_id, metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                        (
                            proposal["title"],
                            f"Auto-created from proposal #{proposal_id}",
                            status,
                            proposal["category"],
                            proposal["priority"],
                            module_id,
                            json.dumps({"proposal_id": proposal_id, "auto_created": True}),
                        ),
                    )

            conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Blueprint update error: {e}")
            raise
        finally:
            cur.close()
            conn.close()

    def _record_deployment_knowledge(
        self,
        proposal_id: int,
        module_id: str,
        title: str,
        success: bool,
        error_message: Optional[str] = None,
    ):
        """Record deployment outcome in knowledge_base"""
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            if success:
                knowledge_type = "improvement"
                importance = 0.6
                content = f"""## Successful Deployment

**Proposal:** #{proposal_id} - {title}
**Module:** {module_id}
**Date:** {datetime.now().isoformat()}

This improvement was successfully deployed to production after passing sandbox tests.
"""
            else:
                knowledge_type = "mistake_learned"
                importance = 0.9
                content = f"""## Failed Deployment

**Proposal:** #{proposal_id} - {title}
**Module:** {module_id}
**Date:** {datetime.now().isoformat()}

**Error:**
{error_message or 'Unknown error'}

This deployment failed during sandbox testing. Investigation required.
"""

            cur.execute(
                """
                INSERT INTO knowledge_base
                (title, content, knowledge_type, importance_score, tags, metadata, source_type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'sandbox_deployment', NOW())
            """,
                (
                    f"{'Deployed' if success else 'Failed'}: {title}",
                    content,
                    knowledge_type,
                    importance,
                    [module_id, "deployment", "sandbox", "auto-recorded"],
                    json.dumps(
                        {
                            "proposal_id": proposal_id,
                            "module_id": module_id,
                            "success": success,
                            "recorded_at": datetime.now().isoformat(),
                        }
                    ),
                ),
            )

            conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Knowledge record error: {e}")
            raise
        finally:
            cur.close()
            conn.close()

    def sync_module_docs(self, module_id: str) -> Dict[str, Any]:
        """
        Sync documentation for a specific module.
        Updates MODULE_REGISTRY_STATUS.md with current status.
        """
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get sandbox status
            cur.execute(
                """
                SELECT status, total_tests_run, tests_passed, tests_failed, last_test_at
                FROM module_sandboxes
                WHERE module_id = %s
            """,
                (module_id,),
            )
            sandbox = cur.fetchone()

            # Get recent proposals
            cur.execute(
                """
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status = 'deployed') as deployed,
                       COUNT(*) FILTER (WHERE status = 'failed') as failed
                FROM improvement_proposals
                WHERE metadata->>'module_id' = %s
                  OR source = 'code_sentinel'
            """,
                (module_id,),
            )
            proposals = cur.fetchone()

            return {
                "success": True,
                "module_id": module_id,
                "sandbox_status": dict(sandbox) if sandbox else None,
                "proposals": dict(proposals) if proposals else None,
            }

        except Exception as e:
            logger.error(f"Sync error: {e}")
            return {"success": False, "error": str(e)}
        finally:
            cur.close()
            conn.close()


# Integration with sandbox_manager
def on_sandbox_test_complete(
    module_id: str,
    proposal_id: Optional[int],
    success: bool,
    test_results: Dict[str, Any],
):
    """
    Hook called when sandbox tests complete.
    Updates documentation based on results.
    """
    updater = SandboxDocsUpdater()

    if proposal_id:
        # Get proposal details
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT title, description, category
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if proposal:
            if success:
                return updater.on_deployment_success(
                    proposal_id=proposal_id,
                    module_id=module_id,
                    title=proposal["title"],
                    description=proposal["description"],
                    category=proposal["category"],
                )
            else:
                return updater.on_deployment_failure(
                    proposal_id=proposal_id,
                    module_id=module_id,
                    title=proposal["title"],
                    error_message=test_results.get("error", "Test failure"),
                    error_details=test_results.get("output", ""),
                )

    return {"success": False, "error": "No proposal ID provided"}


# CLI Testing
if __name__ == "__main__":
    updater = SandboxDocsUpdater()

    # Test successful deployment
    print("Testing successful deployment update...")
    result = updater.on_deployment_success(
        proposal_id=999,
        module_id="test",
        title="Test Proposal",
        description="Testing the docs updater",
        category="feature",
    )
    print(f"Success result: {result}")

    # Test failed deployment
    print("\nTesting failed deployment update...")
    result = updater.on_deployment_failure(
        proposal_id=998,
        module_id="test",
        title="Test Failure Proposal",
        error_message="ImportError: module not found",
        error_details="Stack trace here...",
    )
    print(f"Failure result: {result}")

    print("\nSandbox Docs Updater ready!")
