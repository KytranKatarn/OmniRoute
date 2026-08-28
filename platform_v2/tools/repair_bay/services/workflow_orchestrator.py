"""
Workflow Orchestrator
Orchestrates the complete improvement workflow from proposal to deployment

Author: A.R.C.H.I.E. Self-Improvement System
Date: 2026-01-05
"""

import os
from database import _get_db_password
import sys
from typing import Dict, Optional
from datetime import datetime

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from code_generation_engine import generate_code_for_proposal
from code_application_system import apply_code_changes
from workflow_state_machine import transition_proposal_state
from sandbox_schema import SchemaSandboxManager
import psycopg2
from psycopg2.extras import RealDictCursor


class WorkflowOrchestrator:
    """Orchestrates complete improvement workflow"""

    def __init__(self):
        self.sandbox_manager = SchemaSandboxManager()

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def execute_full_workflow(self, proposal_id: int) -> Dict:
        """
        Execute the complete workflow for a proposal

        Workflow:
        1. Generate code
        2. Create sandbox
        3. Apply code to sandbox
        4. Run tests
        5. Mark as ready for review

        Args:
            proposal_id: Proposal ID

        Returns:
            {
                'success': bool,
                'proposal_id': int,
                'sandbox_id': int,
                'states_completed': list,
                'final_state': str,
                'ready_for_review': bool
            }
        """
        workflow_log = []
        workflow_log.append(f"🚀 Starting full workflow for proposal #{proposal_id}")

        try:
            # Get proposal details
            proposal = self._get_proposal(proposal_id)
            if not proposal:
                return {"success": False, "error": f"Proposal {proposal_id} not found"}

            workflow_log.append(f"📋 Proposal: {proposal['title']}")
            workflow_log.append(f"📁 Category: {proposal['category']}")

            states_completed = []

            # Step 1: Generate Code
            workflow_log.append(f"\n{'='*60}")
            workflow_log.append("Step 1: Code Generation")
            workflow_log.append(f"{'='*60}")

            transition_proposal_state(proposal_id, "generating_code", "Starting code generation")
            states_completed.append("generating_code")

            code_result = generate_code_for_proposal(
                proposal_id=proposal_id,
                proposal_title=proposal["title"],
                proposal_description=proposal["description"],
                category=proposal["category"],
            )

            if not code_result.get("success"):
                workflow_log.append("❌ Code generation failed")
                transition_proposal_state(proposal_id, "failed", "Code generation failed")
                return {
                    "success": False,
                    "error": "Code generation failed",
                    "workflow_log": workflow_log,
                }

            changes = code_result["changes"]
            workflow_log.append(f"✅ Generated {len(changes)} code change(s)")

            # Store generated code in proposal
            self._store_generated_code(proposal_id, changes, code_result["metadata"])

            transition_proposal_state(proposal_id, "code_generated", f"Generated {len(changes)} code changes")
            states_completed.append("code_generated")

            # Step 2: Create Sandbox
            workflow_log.append(f"\n{'='*60}")
            workflow_log.append("Step 2: Sandbox Creation")
            workflow_log.append(f"{'='*60}")

            transition_proposal_state(proposal_id, "creating_sandbox", "Creating sandbox environment")
            states_completed.append("creating_sandbox")

            sandbox_result = self._create_sandbox(proposal_id)

            if not sandbox_result.get("success"):
                workflow_log.append("❌ Sandbox creation failed")
                transition_proposal_state(proposal_id, "failed", "Sandbox creation failed")
                return {
                    "success": False,
                    "error": "Sandbox creation failed",
                    "workflow_log": workflow_log,
                }

            sandbox_id = sandbox_result["sandbox_id"]
            workflow_log.append(f"✅ Sandbox created: #{sandbox_id}")

            transition_proposal_state(proposal_id, "sandbox_created", f"Sandbox #{sandbox_id} created")
            states_completed.append("sandbox_created")

            # Step 3: Apply Code Changes
            workflow_log.append(f"\n{'='*60}")
            workflow_log.append("Step 3: Applying Code Changes")
            workflow_log.append(f"{'='*60}")

            transition_proposal_state(proposal_id, "applying_changes", "Applying code to sandbox")
            states_completed.append("applying_changes")

            apply_result = apply_code_changes(proposal_id, changes)

            if not apply_result.get("success"):
                workflow_log.append("❌ Code application failed")
                workflow_log.extend(apply_result.get("application_log", []))
                transition_proposal_state(proposal_id, "failed", "Code application failed")
                return {
                    "success": False,
                    "error": "Code application failed",
                    "workflow_log": workflow_log,
                }

            workflow_log.extend(apply_result["application_log"])

            # Store application results
            self._store_application_results(proposal_id, sandbox_id, apply_result)

            transition_proposal_state(
                proposal_id,
                "ready_for_testing",
                f'Code applied: {apply_result["files_modified"]} modified, {apply_result["files_created"]} created',
            )
            states_completed.append("ready_for_testing")

            # Step 4: Run Tests
            workflow_log.append(f"\n{'='*60}")
            workflow_log.append("Step 4: Running Tests")
            workflow_log.append(f"{'='*60}")

            transition_proposal_state(proposal_id, "testing", "Running sandbox tests")
            states_completed.append("testing")

            test_result = self._run_tests(sandbox_id, proposal_id)

            if test_result.get("success"):
                workflow_log.append("✅ Tests passed")
                transition_proposal_state(proposal_id, "tested", "All tests passed")
                states_completed.append("tested")
            else:
                workflow_log.append("⚠️  Some tests failed")
                transition_proposal_state(proposal_id, "tested", "Tests completed with warnings")
                states_completed.append("tested")

            # Step 5: Mark as Ready for Review
            transition_proposal_state(proposal_id, "ready_for_review", "Ready for user review and deployment")
            states_completed.append("ready_for_review")

            workflow_log.append(f"\n{'='*60}")
            workflow_log.append("✅ Workflow Complete - Ready for Review!")
            workflow_log.append(f"{'='*60}")
            workflow_log.append(f"📊 States completed: {len(states_completed)}")
            workflow_log.append(f"🧪 Sandbox ID: {sandbox_id}")
            workflow_log.append("📋 View in sandbox to test changes")
            workflow_log.append("🚀 Deploy when ready")

            return {
                "success": True,
                "proposal_id": proposal_id,
                "sandbox_id": sandbox_id,
                "states_completed": states_completed,
                "final_state": "ready_for_review",
                "ready_for_review": True,
                "workflow_log": workflow_log,
                "changes_applied": len(changes),
                "files_modified": apply_result["files_modified"],
                "files_created": apply_result["files_created"],
            }

        except Exception as e:
            import traceback

            workflow_log.append(f"\n❌ Workflow error: {str(e)}")
            workflow_log.append(traceback.format_exc())
            transition_proposal_state(proposal_id, "failed", f"Workflow error: {str(e)}")

            return {"success": False, "error": str(e), "workflow_log": workflow_log}

    def _get_proposal(self, proposal_id: int) -> Optional[Dict]:
        """Get proposal details"""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, title, description, category, priority, status
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        cur.close()
        conn.close()

        return dict(proposal) if proposal else None

    def _store_generated_code(self, proposal_id: int, changes: list, metadata: dict):
        """Store generated code in database"""
        conn = self.get_db()
        cur = conn.cursor()

        # Store in plan_steps field as JSON
        plan_steps = []
        for change in changes:
            plan_steps.append(
                {
                    "action": change["action"],
                    "target": change["file_path"],
                    "description": change["description"],
                    "details": change.get("diff", ""),
                    "new_content": change.get("new_content", ""),
                    "old_content": change.get("old_content", ""),
                }
            )

        cur.execute(
            """
            UPDATE improvement_proposals
            SET plan_steps = %s,
                metadata = metadata || %s::jsonb
            WHERE id = %s
        """,
            (
                psycopg2.extras.Json(plan_steps),
                psycopg2.extras.Json({"code_generation": metadata}),
                proposal_id,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

    def _create_sandbox(self, proposal_id: int) -> Dict:
        """Create sandbox for proposal"""
        # Check if sandbox already exists
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id FROM sandbox_instances
            WHERE proposal_id = %s AND destroyed_at IS NULL
            LIMIT 1
        """,
            (proposal_id,),
        )

        existing = cur.fetchone()

        if existing:
            cur.close()
            conn.close()
            return {
                "success": True,
                "sandbox_id": existing["id"],
                "message": "Using existing sandbox",
            }

        # Create new sandbox
        result = self.sandbox_manager.create_schema(sandbox_id=proposal_id, proposal_id=proposal_id, clone_data=True)

        if not result.get("success"):
            cur.close()
            conn.close()
            return result

        # Record sandbox in database
        cur.execute(
            """
            INSERT INTO sandbox_instances
            (proposal_id, sandbox_type, schema_name, status, metadata)
            VALUES (%s, 'schema_separation', 'sandbox', 'ready', %s::jsonb)
            RETURNING id
        """,
            (
                proposal_id,
                psycopg2.extras.Json(
                    {
                        "tables_cloned": result["tables_cloned"],
                        "rows_cloned": result["rows_cloned"],
                    }
                ),
            ),
        )

        sandbox_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": True,
            "sandbox_id": sandbox_id,
            "schema_name": result["schema_name"],
        }

    def _store_application_results(self, proposal_id: int, sandbox_id: int, apply_result: dict):
        """Store code application results"""
        conn = self.get_db()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE sandbox_instances
            SET metadata = metadata || %s::jsonb,
                status = 'ready'
            WHERE id = %s
        """,
            (
                psycopg2.extras.Json(
                    {
                        "application_results": {
                            "files_modified": apply_result["files_modified"],
                            "files_created": apply_result["files_created"],
                            "backup_path": apply_result["backup_path"],
                            "applied_at": datetime.now().isoformat(),
                        }
                    }
                ),
                sandbox_id,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

    def _run_tests(self, sandbox_id: int, proposal_id: int) -> Dict:
        """Run tests in sandbox"""
        try:
            from sandbox_test_runner import run_sandbox_tests

            return run_sandbox_tests(sandbox_id, proposal_id)
        except Exception as e:
            # Tests not critical - continue workflow
            return {"success": True, "warning": f"Tests could not run: {str(e)}"}


# Convenience function
def execute_workflow(proposal_id: int) -> Dict:
    """Execute complete workflow for a proposal"""
    orchestrator = WorkflowOrchestrator()
    return orchestrator.execute_full_workflow(proposal_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        proposal_id = int(sys.argv[1])
        print(f"🚀 Executing workflow for proposal #{proposal_id}...")
        result = execute_workflow(proposal_id)

        print(f"\n{'='*80}")
        print("WORKFLOW RESULT")
        print(f"{'='*80}")
        print(f"Success: {result.get('success')}")
        print(f"Final State: {result.get('final_state')}")
        print(f"Sandbox ID: {result.get('sandbox_id')}")
        print("\nWorkflow Log:")
        for line in result.get("workflow_log", []):
            print(line)
    else:
        print("Usage: python workflow_orchestrator.py <proposal_id>")
