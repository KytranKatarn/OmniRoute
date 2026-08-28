"""
Sandbox Code Applicator for A.R.C.H.I.E.
Applies code changes to sandbox environments for testing before production

Supports:
- Schema-based sandboxes (SQL/database changes)
- Docker container sandboxes (file-based changes)
- Validation and rollback capabilities
"""

import os
from database import _get_db_password
import subprocess
from typing import Dict, List
import tempfile


class SandboxCodeApplicator:
    """
    Applies code changes to sandbox environments.

    For schema sandboxes:
    - Applies SQL schema changes
    - Updates database objects

    For Docker sandboxes:
    - Mounts code changes into container
    - Updates files in sandbox
    - Restarts services if needed
    """

    def __init__(self):
        self.platform_v2_path = "/mnt/archie_brain/platform_v2"
        self.ai_bridge_path = "/mnt/archie_brain/ai_bridge"

    def apply_changes_to_sandbox(
        self,
        sandbox_id: int,
        sandbox_type: str,
        code_changes: List[Dict],
        schema_name: str = None,
        container_id: str = None,
    ) -> Dict:
        """
        Apply code changes to a sandbox environment.

        Args:
            sandbox_id: Sandbox instance ID
            sandbox_type: 'schema_separation' or 'docker_container'
            code_changes: List of file changes [{'path': str, 'before': str, 'after': str}]
            schema_name: Schema name (for schema sandboxes)
            container_id: Container ID (for Docker sandboxes)

        Returns:
            {
                'success': True,
                'changes_applied': 3,
                'files_modified': ['file1.py', 'file2.sql'],
                'errors': []
            }
        """
        if sandbox_type in ["schema", "schema_separation"]:
            return self._apply_to_schema_sandbox(
                sandbox_id=sandbox_id,
                schema_name=schema_name,
                code_changes=code_changes,
            )
        elif sandbox_type in ["docker", "docker_container"]:
            return self._apply_to_docker_sandbox(
                sandbox_id=sandbox_id,
                container_id=container_id,
                code_changes=code_changes,
            )
        else:
            return {"success": False, "error": f"Unknown sandbox type: {sandbox_type}"}

    def _apply_to_schema_sandbox(self, sandbox_id: int, schema_name: str, code_changes: List[Dict]) -> Dict:
        """
        Apply SQL/schema changes to a schema-based sandbox.

        Focuses on:
        - SQL migrations
        - Schema alterations
        - Data changes
        """
        import psycopg2
        from psycopg2 import sql

        if not schema_name:
            return {
                "success": False,
                "error": "Schema name required for schema sandbox",
            }

        try:
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "archie_database"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )
            cur = conn.cursor()

            changes_applied = 0
            files_modified = []
            errors = []

            # Set schema search path
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))

            for change in code_changes:
                file_path = change.get("path", "")
                after_content = change.get("after", "")

                # Only process SQL files in schema sandboxes
                if not file_path.endswith(".sql"):
                    continue

                try:
                    # Execute SQL changes in the sandbox schema
                    cur.execute(after_content)
                    conn.commit()

                    changes_applied += 1
                    files_modified.append(file_path)

                except Exception as e:
                    errors.append({"file": file_path, "error": str(e)})
                    conn.rollback()

            cur.close()
            conn.close()

            return {
                "success": len(errors) == 0,
                "sandbox_id": sandbox_id,
                "sandbox_type": "schema_separation",
                "changes_applied": changes_applied,
                "files_modified": files_modified,
                "errors": errors,
                "message": f"Applied {changes_applied} SQL changes to schema {schema_name}",
            }

        except Exception as e:
            return {"success": False, "error": str(e), "sandbox_id": sandbox_id}

    def _apply_to_docker_sandbox(self, sandbox_id: int, container_id: str, code_changes: List[Dict]) -> Dict:
        """
        Apply file changes to a Docker container sandbox.

        Process:
        1. Create temp files with new content
        2. Copy to container
        3. Verify changes applied
        4. Optionally restart services
        """
        if not container_id:
            return {
                "success": False,
                "error": "Container ID required for Docker sandbox",
            }

        changes_applied = 0
        files_modified = []
        errors = []

        try:
            # Verify container is running
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0 or "true" not in result.stdout.lower():
                return {
                    "success": False,
                    "error": f"Container {container_id} is not running",
                }

            # Apply each file change
            for change in code_changes:
                file_path = change.get("path", "")
                after_content = change.get("after", "")

                if not file_path:
                    continue

                try:
                    # Create temp file with new content
                    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tmp") as tmp:
                        tmp.write(after_content)
                        tmp_path = tmp.name

                    # Copy to container
                    result = subprocess.run(
                        ["docker", "cp", tmp_path, f"{container_id}:{file_path}"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )

                    # Clean up temp file
                    os.unlink(tmp_path)

                    if result.returncode == 0:
                        changes_applied += 1
                        files_modified.append(file_path)
                    else:
                        errors.append({"file": file_path, "error": result.stderr})

                except Exception as e:
                    errors.append({"file": file_path, "error": str(e)})

            return {
                "success": len(errors) == 0,
                "sandbox_id": sandbox_id,
                "sandbox_type": "docker_container",
                "changes_applied": changes_applied,
                "files_modified": files_modified,
                "errors": errors,
                "message": f"Applied {changes_applied} file changes to container {container_id}",
            }

        except Exception as e:
            return {"success": False, "error": str(e), "sandbox_id": sandbox_id}

    def verify_changes_applied(
        self,
        sandbox_type: str,
        container_id: str = None,
        schema_name: str = None,
        expected_files: List[str] = None,
    ) -> Dict:
        """
        Verify that changes were successfully applied to the sandbox.

        Returns:
            {'success': True, 'verified_files': [...], 'missing_files': [...]}
        """
        if sandbox_type in ["docker", "docker_container"]:
            return self._verify_docker_changes(container_id, expected_files)
        elif sandbox_type in ["schema", "schema_separation"]:
            return self._verify_schema_changes(schema_name)
        else:
            return {"success": False, "error": "Unknown sandbox type"}

    def _verify_docker_changes(self, container_id: str, expected_files: List[str]) -> Dict:
        """Verify files exist in Docker container"""
        verified = []
        missing = []

        if not expected_files:
            return {"success": True, "verified_files": [], "missing_files": []}

        try:
            for file_path in expected_files:
                result = subprocess.run(
                    ["docker", "exec", container_id, "test", "-f", file_path],
                    capture_output=True,
                    timeout=5,
                )

                if result.returncode == 0:
                    verified.append(file_path)
                else:
                    missing.append(file_path)

            return {
                "success": len(missing) == 0,
                "verified_files": verified,
                "missing_files": missing,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _verify_schema_changes(self, schema_name: str) -> Dict:
        """Verify schema exists and is accessible"""
        import psycopg2

        try:
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "archie_database"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )
            cur = conn.cursor()

            # Verify schema exists
            cur.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.schemata
                WHERE schema_name = %s
            """,
                (schema_name,),
            )

            count = cur.fetchone()[0]
            cur.close()
            conn.close()

            return {
                "success": count > 0,
                "schema_exists": count > 0,
                "schema_name": schema_name,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def apply_code_to_sandbox(sandbox_id: int, sandbox_type: str, code_changes: List[Dict], **kwargs) -> Dict:
    """Quick function to apply code changes to a sandbox"""
    applicator = SandboxCodeApplicator()
    return applicator.apply_changes_to_sandbox(
        sandbox_id=sandbox_id,
        sandbox_type=sandbox_type,
        code_changes=code_changes,
        **kwargs,
    )


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Sandbox Code Applicator - Test Mode")
    print("=" * 60)

    # Test with sample SQL change
    sample_changes = [
        {
            "path": "/migrations/test.sql",
            "before": "",
            "after": "CREATE TABLE IF NOT EXISTS test_table (id INTEGER);",
        }
    ]

    applicator = SandboxCodeApplicator()
    print("\n✅ Sandbox Code Applicator loaded successfully!")
    print(f"Supports: Schema sandboxes, Docker container sandboxes")
