"""
Sandbox Manager for A.R.C.H.I.E. Improvement Workflow
Orchestrates sandbox creation, testing, and cleanup for safe code changes

Supports two sandbox types:
1. Docker Container - Full isolated environment for high-risk changes
2. Schema Separation - Database-level isolation for low-risk changes
"""

import os
from database import _get_db_password
import subprocess
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, Literal, List
import json
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Docker SDK for container management
try:
    import docker

    DOCKER_AVAILABLE = True
except ImportError:
    docker = None
    DOCKER_AVAILABLE = False
    logger.warning("Docker SDK not available - container management disabled")

try:
    from tools.repair_bay.services.sandbox_docker import DockerSandboxManager
except ImportError as e:
    DockerSandboxManager = None
    logger.info(f"DockerSandboxManager not available: {e}")

try:
    from tools.repair_bay.services.sandbox_schema import SchemaSandboxManager
except ImportError as e:
    SchemaSandboxManager = None
    logger.info(f"SchemaSandboxManager not available: {e}")

try:
    from tools.repair_bay.services.sandbox_test_runner import SandboxTestRunner
except ImportError as e:
    SandboxTestRunner = None
    logger.info(f"SandboxTestRunner not available: {e}")

try:
    from tools.repair_bay.services.sandbox_code_applicator import SandboxCodeApplicator
except ImportError as e:
    SandboxCodeApplicator = None
    logger.info(f"SandboxCodeApplicator not available: {e}")


class SandboxManager:
    """
    Main orchestrator for sandbox lifecycle management.

    Workflow:
    1. Analyze proposal risk/complexity
    2. Choose sandbox type (Docker vs Schema)
    3. Create sandbox instance
    4. Apply code changes
    5. Run tests
    6. Report results
    7. Cleanup (manual or auto)
    """

    def __init__(self):
        self.docker_manager = DockerSandboxManager() if DockerSandboxManager else None
        self.schema_manager = SchemaSandboxManager() if SchemaSandboxManager else None
        self.test_runner = SandboxTestRunner() if SandboxTestRunner else None
        self.code_applicator = SandboxCodeApplicator() if SandboxCodeApplicator else None

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def determine_sandbox_type(
        self,
        proposal_id: int = None,
        priority: str = None,
        complexity: str = None,
        category: str = None,
        user_override: str = None,
    ) -> Literal["docker_container", "schema_separation"]:
        """
        Determine which sandbox type to use based on risk assessment.

        Decision Logic:
        - User override takes precedence
        - High priority OR high complexity → Docker
        - Security/database/architecture category → Docker
        - Everything else → Schema (faster, lighter)

        Args:
            proposal_id: Load from database if provided
            priority: Priority level (low/medium/high/critical)
            complexity: Complexity level (low/medium/high)
            category: Category (security, database, etc.)
            user_override: Force 'docker_container' or 'schema_separation'

        Returns:
            'docker_container' or 'schema_separation'
        """
        # User override - support both old and new naming
        if user_override in ["docker", "docker_container"]:
            return "docker_container"
        if user_override in ["schema", "schema_separation"]:
            return "schema_separation"

        # Load from database if proposal_id provided
        if proposal_id:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT priority, complexity, category
                FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row:
                priority = priority or row.get("priority")
                complexity = complexity or row.get("complexity")
                category = category or row.get("category")

        # High-risk categories always use Docker
        high_risk_categories = [
            "security",
            "database",
            "architecture",
            "performance",
            "api",
            "infrastructure",
        ]
        if category in high_risk_categories:
            return "docker_container"

        # High priority/complexity use Docker
        if priority in ["high", "critical"]:
            return "docker_container"

        if complexity == "high":
            return "docker_container"

        # Default to schema (faster, lighter)
        return "schema_separation"

    def create_sandbox(
        self,
        proposal_id: int,
        sandbox_type: str = None,
        backup_ref: str = None,
        metadata: Dict = None,
    ) -> Dict:
        """
        Create a new sandbox instance for testing.

        Args:
            proposal_id: Improvement proposal ID
            sandbox_type: 'docker' or 'schema' (auto-determined if None)
            backup_ref: Reference to pre-deployment backup
            metadata: Additional metadata

        Returns:
            {
                'success': True,
                'sandbox_id': 123,
                'sandbox_type': 'docker',
                'container_id': 'abc123...' (if Docker),
                'schema_name': 'sandbox_123' (if Schema),
                'status': 'ready',
                'created_at': '2026-01-01T...'
            }
        """
        # Determine sandbox type if not specified
        if not sandbox_type:
            sandbox_type = self.determine_sandbox_type(proposal_id=proposal_id)

        # Validate sandbox type
        if sandbox_type not in ["docker_container", "schema_separation"]:
            return {
                "success": False,
                "error": f"Invalid sandbox type: {sandbox_type}. Must be 'docker_container' or 'schema_separation'",
            }

        # Check if managers are available
        if sandbox_type == "docker_container" and not self.docker_manager:
            return {"success": False, "error": "Docker sandbox manager not available"}

        if sandbox_type == "schema_separation" and not self.schema_manager:
            return {"success": False, "error": "Schema sandbox manager not available"}

        # Auto-cleanup: Destroy old sandboxes to keep only one active at a time
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find and destroy any old active sandboxes
        cur.execute(
            """
            SELECT id, sandbox_type, schema_name, container_id
            FROM sandbox_instances
            WHERE destroyed_at IS NULL
            AND status NOT IN ('destroying', 'destroyed')
            ORDER BY created_at DESC
        """
        )
        old_sandboxes = cur.fetchall()

        for old_sandbox in old_sandboxes:
            old_id = old_sandbox["id"]
            old_type = old_sandbox["sandbox_type"]

            # Destroy the old sandbox
            if old_type == "schema_separation" and old_sandbox["schema_name"]:
                try:
                    # Drop the old schema
                    cur.execute(f"DROP SCHEMA IF EXISTS {old_sandbox['schema_name']} CASCADE")
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Could not drop schema {old_sandbox['schema_name']}: {e}")

            elif old_type == "docker_container" and old_sandbox["container_id"]:
                try:
                    # Stop and remove the container
                    subprocess.run(
                        ["docker", "stop", old_sandbox["container_id"]],
                        capture_output=True,
                        timeout=30,
                    )
                    subprocess.run(
                        ["docker", "rm", old_sandbox["container_id"]],
                        capture_output=True,
                        timeout=30,
                    )
                except Exception as e:
                    logger.warning(f"Could not remove container {old_sandbox['container_id']}: {e}")

            # Mark as destroyed in database
            cur.execute(
                """
                UPDATE sandbox_instances
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE id = %s
            """,
                (old_id,),
            )
            conn.commit()
            logger.info(f"Cleaned up old sandbox #{old_id}")

        # Create sandbox instance record
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO sandbox_instances
            (proposal_id, sandbox_type, status, backup_ref, metadata)
            VALUES (%s, %s, 'creating', %s, %s)
            RETURNING id, created_at;
        """,
            (proposal_id, sandbox_type, backup_ref, json.dumps(metadata or {})),
        )

        result = dict(cur.fetchone())
        sandbox_id = result["id"]

        conn.commit()

        try:
            # Create actual sandbox
            if sandbox_type == "docker_container":
                sandbox_result = self.docker_manager.create_container(sandbox_id=sandbox_id, proposal_id=proposal_id)

                if sandbox_result["success"]:
                    # Update with container info
                    cur.execute(
                        """
                        UPDATE sandbox_instances
                        SET container_id = %s,
                            status = 'ready',
                            metadata = metadata || %s::jsonb
                        WHERE id = %s
                    """,
                        (
                            sandbox_result["container_id"],
                            json.dumps(
                                {
                                    "container_name": sandbox_result.get("container_name"),
                                    "ports": sandbox_result.get("ports"),
                                }
                            ),
                            sandbox_id,
                        ),
                    )
                    conn.commit()
                else:
                    # Mark as failed
                    cur.execute(
                        """
                        UPDATE sandbox_instances
                        SET status = 'failed',
                            metadata = metadata || %s::jsonb
                        WHERE id = %s
                    """,
                        (
                            json.dumps({"error": sandbox_result.get("error")}),
                            sandbox_id,
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    return sandbox_result

            elif sandbox_type == "schema_separation":
                sandbox_result = self.schema_manager.create_schema(sandbox_id=sandbox_id, proposal_id=proposal_id)

                if sandbox_result["success"]:
                    # Update with schema info
                    cur.execute(
                        """
                        UPDATE sandbox_instances
                        SET schema_name = %s,
                            status = 'ready',
                            metadata = metadata || %s::jsonb
                        WHERE id = %s
                    """,
                        (
                            sandbox_result["schema_name"],
                            json.dumps({"tables_cloned": sandbox_result.get("tables_cloned", 0)}),
                            sandbox_id,
                        ),
                    )
                    conn.commit()
                else:
                    # Mark as failed
                    cur.execute(
                        """
                        UPDATE sandbox_instances
                        SET status = 'failed',
                            metadata = metadata || %s::jsonb
                        WHERE id = %s
                    """,
                        (
                            json.dumps({"error": sandbox_result.get("error")}),
                            sandbox_id,
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    return sandbox_result

            # Refresh data
            cur.execute(
                """
                SELECT * FROM sandbox_instances WHERE id = %s
            """,
                (sandbox_id,),
            )
            final_result = dict(cur.fetchone())

            cur.close()
            conn.close()

            return {
                "success": True,
                "sandbox_id": final_result["id"],
                "sandbox_type": final_result["sandbox_type"],
                "container_id": final_result.get("container_id"),
                "schema_name": final_result.get("schema_name"),
                "status": final_result["status"],
                "created_at": final_result["created_at"].isoformat(),
            }

        except Exception as e:
            # Update status to failed
            cur.execute(
                """
                UPDATE sandbox_instances
                SET status = 'failed',
                    metadata = metadata || %s::jsonb
                WHERE id = %s
            """,
                (json.dumps({"error": str(e)}), sandbox_id),
            )
            conn.commit()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e), "sandbox_id": sandbox_id}

    def run_tests(self, sandbox_id: int, test_suite: str = "default") -> Dict:
        """
        Run tests in the sandbox.

        Args:
            sandbox_id: Sandbox instance ID
            test_suite: Which tests to run ('default', 'security', 'performance', etc.)

        Returns:
            {
                'success': True,
                'tests_passed': 45,
                'tests_failed': 2,
                'tests_total': 47,
                'pass_rate': 95.7,
                'results': [...]
            }
        """
        if not self.test_runner:
            return {"success": False, "error": "Test runner not available"}

        # Get sandbox info
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT * FROM sandbox_instances WHERE id = %s
        """,
            (sandbox_id,),
        )
        sandbox = cur.fetchone()

        if not sandbox:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Sandbox {sandbox_id} not found"}

        if sandbox["status"] != "ready":
            cur.close()
            conn.close()
            return {
                "success": False,
                "error": f"Sandbox status is '{sandbox['status']}', must be 'ready'",
            }

        # Update status to testing
        cur.execute(
            """
            UPDATE sandbox_instances
            SET status = 'testing'
            WHERE id = %s
        """,
            (sandbox_id,),
        )
        conn.commit()

        try:
            # Run tests
            test_result = self.test_runner.run_tests(
                sandbox_id=sandbox_id,
                sandbox_type=sandbox["sandbox_type"],
                container_id=sandbox.get("container_id"),
                schema_name=sandbox.get("schema_name"),
                test_suite=test_suite,
            )

            # Store results
            cur.execute(
                """
                UPDATE sandbox_instances
                SET test_results = %s,
                    status = 'tested',
                    metadata = metadata || %s::jsonb
                WHERE id = %s
            """,
                (
                    json.dumps(test_result),
                    json.dumps(
                        {
                            "last_test_run": datetime.now().isoformat(),
                            "test_suite": test_suite,
                        }
                    ),
                    sandbox_id,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

            return test_result

        except Exception as e:
            # Mark as failed
            cur.execute(
                """
                UPDATE sandbox_instances
                SET status = 'test_failed',
                    metadata = metadata || %s::jsonb
                WHERE id = %s
            """,
                (json.dumps({"test_error": str(e)}), sandbox_id),
            )
            conn.commit()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def run_tests_for_proposal(self, proposal_id: int, test_suite: str = "default") -> Dict:
        """Create a sandbox for a proposal, run its tests, return an auto_run-shaped result.

        Bridges proposal_service.auto_run (#4249): it called this method, which never
        existed, so every approved->testing transition hit AttributeError and silently
        degraded to "tests unavailable". Composes the existing create_sandbox + run_tests
        primitives and maps run_tests' {tests_passed/tests_failed/pass_rate} output to the
        {overall_status, summary} contract auto_run consumes.

        Raises on sandbox-infra / creation / run failure so auto_run's except handler keeps
        the existing graceful "tests unavailable -> ready for manual review" behaviour,
        rather than wrongly flagging the proposal as needing fixes when the sandbox layer
        is simply unavailable.
        """
        created = self.create_sandbox(proposal_id)
        if not created or not created.get("success"):
            raise RuntimeError((created or {}).get("error", "sandbox creation failed"))
        sandbox_id = created.get("sandbox_id")
        if not sandbox_id:
            raise RuntimeError("sandbox created but no sandbox_id returned")

        result = self.run_tests(sandbox_id, test_suite)
        if not result or not result.get("success"):
            raise RuntimeError((result or {}).get("error", "test run failed"))

        passed = result.get("tests_passed", 0)
        failed = result.get("tests_failed", 0)
        total = result.get("tests_total", passed + failed)
        return {
            "overall_status": "passed" if failed == 0 else "failed",
            "summary": f"{passed}/{total} tests passed ({result.get('pass_rate', 0)}% pass rate)",
            "sandbox_id": sandbox_id,
            **result,
        }

    def apply_code_changes(self, sandbox_id: int, code_changes: List[Dict]) -> Dict:
        """
        Apply code changes to a sandbox before testing.

        Args:
            sandbox_id: Sandbox instance ID
            code_changes: List of file changes [{'path': str, 'before': str, 'after': str}]

        Returns:
            {
                'success': True,
                'changes_applied': 3,
                'files_modified': ['file1.py', 'file2.sql']
            }
        """
        if not self.code_applicator:
            return {"success": False, "error": "Code applicator not available"}

        # Get sandbox info
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT * FROM sandbox_instances WHERE id = %s
        """,
            (sandbox_id,),
        )
        sandbox = cur.fetchone()

        if not sandbox:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Sandbox {sandbox_id} not found"}

        # Update status to applying_changes
        cur.execute(
            """
            UPDATE sandbox_instances
            SET status = 'applying_changes',
                metadata = metadata || %s::jsonb
            WHERE id = %s
        """,
            (
                json.dumps({"code_changes_started": datetime.now().isoformat()}),
                sandbox_id,
            ),
        )
        conn.commit()

        try:
            # Apply changes
            result = self.code_applicator.apply_changes_to_sandbox(
                sandbox_id=sandbox_id,
                sandbox_type=sandbox["sandbox_type"],
                code_changes=code_changes,
                schema_name=sandbox.get("schema_name"),
                container_id=sandbox.get("container_id"),
            )

            # Update sandbox with results
            new_status = "ready" if result["success"] else "apply_failed"
            cur.execute(
                """
                UPDATE sandbox_instances
                SET status = %s,
                    metadata = metadata || %s::jsonb
                WHERE id = %s
            """,
                (
                    new_status,
                    json.dumps(
                        {
                            "changes_applied": result.get("changes_applied", 0),
                            "files_modified": result.get("files_modified", []),
                            "apply_errors": result.get("errors", []),
                            "code_changes_completed": datetime.now().isoformat(),
                        }
                    ),
                    sandbox_id,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

            return result

        except Exception as e:
            # Mark as failed
            cur.execute(
                """
                UPDATE sandbox_instances
                SET status = 'apply_failed',
                    metadata = metadata || %s::jsonb
                WHERE id = %s
            """,
                (json.dumps({"apply_error": str(e)}), sandbox_id),
            )
            conn.commit()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def destroy_sandbox(self, sandbox_id: int, force: bool = False) -> Dict:
        """
        Destroy a sandbox instance and cleanup resources.

        Args:
            sandbox_id: Sandbox instance ID
            force: Force destruction even if tests are running

        Returns:
            {
                'success': True,
                'sandbox_id': 123,
                'destroyed_at': '2026-01-01T...'
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM sandbox_instances WHERE id = %s
        """,
            (sandbox_id,),
        )
        sandbox = cur.fetchone()

        if not sandbox:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Sandbox {sandbox_id} not found"}

        # Check status
        if sandbox["status"] == "testing" and not force:
            cur.close()
            conn.close()
            return {
                "success": False,
                "error": "Tests are running. Use force=True to destroy anyway.",
            }

        try:
            # Destroy actual sandbox
            if sandbox["sandbox_type"] == "docker_container":
                if self.docker_manager:
                    destroy_result = self.docker_manager.destroy_container(container_id=sandbox.get("container_id"))
                    if not destroy_result["success"]:
                        cur.close()
                        conn.close()
                        return destroy_result

            elif sandbox["sandbox_type"] == "schema_separation":
                if self.schema_manager:
                    destroy_result = self.schema_manager.destroy_schema(schema_name=sandbox.get("schema_name"))
                    if not destroy_result["success"]:
                        cur.close()
                        conn.close()
                        return destroy_result

            # Update database
            cur.execute(
                """
                UPDATE sandbox_instances
                SET status = 'destroyed',
                    destroyed_at = NOW()
                WHERE id = %s
                RETURNING destroyed_at;
            """,
                (sandbox_id,),
            )

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            return {
                "success": True,
                "sandbox_id": sandbox_id,
                "destroyed_at": result["destroyed_at"].isoformat(),
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {"success": False, "error": str(e)}

    def get_sandbox_status(self, sandbox_id: int) -> Dict:
        """
        Get current sandbox status and details.

        Returns:
            {
                'sandbox_id': 123,
                'proposal_id': 456,
                'sandbox_type': 'docker',
                'status': 'ready',
                'created_at': '...',
                'test_results': {...},
                'metadata': {...}
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM sandbox_instances WHERE id = %s
        """,
            (sandbox_id,),
        )

        sandbox = cur.fetchone()
        cur.close()
        conn.close()

        if not sandbox:
            return {"success": False, "error": f"Sandbox {sandbox_id} not found"}

        return dict(sandbox)

    def list_sandboxes(self, proposal_id: int = None, status: str = None, limit: int = 20) -> Dict:
        """
        List sandbox instances with optional filters.

        Returns:
            {
                'success': True,
                'sandboxes': [...],
                'total': 5
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = "SELECT * FROM sandbox_instances WHERE 1=1"
        params = []

        if proposal_id:
            query += " AND proposal_id = %s"
            params.append(proposal_id)

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        sandboxes = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "success": True,
            "sandboxes": [dict(s) for s in sandboxes],
            "total": len(sandboxes),
        }

    # ========================================================================
    # MODULE SANDBOX METHODS
    # Per-module sandbox support for isolated testing
    # ========================================================================

    def get_module_sandboxes(self) -> Dict:
        """Get all module sandboxes with their current status"""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                ms.*,
                ip.title AS proposal_title,
                ip.category AS proposal_category,
                ip.priority AS proposal_priority
            FROM module_sandboxes ms
            LEFT JOIN improvement_proposals ip ON ms.current_proposal_id = ip.id
            ORDER BY ms.port
        """
        )
        sandboxes = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "success": True,
            "sandboxes": [dict(s) for s in sandboxes],
            "total": len(sandboxes),
        }

    def get_module_sandbox(self, module_id: str) -> Dict:
        """Get sandbox info for a specific module"""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get server host for remote access
        server_host = os.getenv("SERVER_HOST", "192.168.1.200")

        cur.execute(
            """
            SELECT
                ms.*,
                ip.title AS proposal_title,
                ip.category AS proposal_category,
                ip.priority AS proposal_priority,
                CASE
                    WHEN ms.status = 'active' THEN 'http://' || %s || ':' || ms.port || '/sandbox/dashboard'
                    ELSE NULL
                END AS access_url
            FROM module_sandboxes ms
            LEFT JOIN improvement_proposals ip ON ms.current_proposal_id = ip.id
            WHERE ms.module_id = %s
        """,
            (server_host, module_id),
        )
        sandbox = cur.fetchone()

        cur.close()
        conn.close()

        if not sandbox:
            return {"success": False, "error": f"Module sandbox not found: {module_id}"}

        return {"success": True, "sandbox": dict(sandbox)}

    def create_module_sandbox(self, module_id: str, proposal_id: int = None) -> Dict:
        """
        Create/activate a module-specific sandbox.

        Args:
            module_id: Module identifier (bridge, improvements, etc.)
            proposal_id: Optional proposal to associate

        Returns:
            Sandbox info including access URL
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get module sandbox config
        cur.execute(
            """
            SELECT * FROM module_sandboxes WHERE module_id = %s
        """,
            (module_id,),
        )
        sandbox = cur.fetchone()

        if not sandbox:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Unknown module: {module_id}"}

        sandbox_type = sandbox["sandbox_type"]
        schema_name = sandbox["schema_name"]
        port = sandbox["port"]

        try:
            # Create schema if using schema-based sandbox
            if sandbox_type == "schema" and self.schema_manager:
                # Create the schema sandbox
                result = self.schema_manager.create_schema(sandbox_id=sandbox["id"], proposal_id=proposal_id or 0)
                if not result.get("success"):
                    cur.close()
                    conn.close()
                    return result

            # Start the Docker container for this sandbox
            container_name = sandbox.get("container_name", f"archie_sandbox_{module_id}")

            # Start container using Docker SDK
            logger.info(f"Starting sandbox container for {module_id} on port {port}")
            container_started = False
            try:
                if DOCKER_AVAILABLE:
                    client = docker.from_env()
                    try:
                        # Check if container exists
                        container = client.containers.get(container_name)
                        if container.status != "running":
                            container.start()
                            logger.info(f"Container {container_name} started")
                        else:
                            logger.info(f"Container {container_name} already running")
                        container_started = True
                    except docker.errors.NotFound:
                        # Container doesn't exist - try docker-compose
                        logger.info(f"Container {container_name} not found, using docker-compose")
                        result = subprocess.run(
                            [
                                "docker",
                                "compose",
                                "-f",
                                "/mnt/archie_brain/docker-compose.sandbox.yml",
                                "--profile",
                                f"sandbox_{module_id}",
                                "up",
                                "-d",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=180,
                        )
                        if result.returncode == 0:
                            container_started = True
                            logger.info(f"Container {container_name} created and started")
                        else:
                            logger.warning(f"docker-compose failed: {result.stderr}")
                else:
                    # Fallback to subprocess
                    result = subprocess.run(
                        [
                            "docker",
                            "compose",
                            "-f",
                            "/mnt/archie_brain/docker-compose.sandbox.yml",
                            "--profile",
                            f"sandbox_{module_id}",
                            "up",
                            "-d",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    container_started = result.returncode == 0
            except Exception as docker_err:
                logger.error(f"Failed to start Docker container: {docker_err}")
                # Continue anyway - schema sandbox might still work

            # Update module sandbox status
            cur.execute(
                """
                UPDATE module_sandboxes
                SET status = 'active',
                    current_proposal_id = %s,
                    last_used_at = NOW()
                WHERE module_id = %s
                RETURNING *
            """,
                (proposal_id, module_id),
            )
            updated = cur.fetchone()
            conn.commit()

            cur.close()
            conn.close()

            # Get server host for remote access
            server_host = os.getenv("SERVER_HOST", "192.168.1.200")
            access_url = f"http://{server_host}:{port}/sandbox/dashboard"

            return {
                "success": True,
                "sandbox_id": updated["id"],
                "module_id": module_id,
                "sandbox_type": sandbox_type,
                "schema_name": schema_name,
                "port": port,
                "status": "active",
                "access_url": access_url,
                "proposal_id": proposal_id,
                "container_name": container_name,
            }

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return {"success": False, "error": str(e)}

    def destroy_module_sandbox(self, module_id: str) -> Dict:
        """Destroy/deactivate a module sandbox"""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM module_sandboxes WHERE module_id = %s
        """,
            (module_id,),
        )
        sandbox = cur.fetchone()

        if not sandbox:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Unknown module: {module_id}"}

        try:
            # Stop the Docker container first
            container_name = sandbox.get("container_name", f"archie_sandbox_{module_id}")
            logger.info(f"Stopping sandbox container for {module_id}")

            try:
                if DOCKER_AVAILABLE:
                    client = docker.from_env()
                    try:
                        container = client.containers.get(container_name)
                        if container.status == "running":
                            container.stop(timeout=30)
                            logger.info(f"Container {container_name} stopped")
                    except docker.errors.NotFound:
                        logger.info(f"Container {container_name} not found (already stopped)")
                else:
                    # Fallback to subprocess
                    subprocess.run(
                        ["docker", "stop", container_name],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    logger.info(f"Container stopped for {module_id}")
            except Exception as docker_err:
                logger.warning(f"Failed to stop Docker container: {docker_err}")

            # Drop schema if schema-based
            if sandbox["sandbox_type"] == "schema" and sandbox["schema_name"]:
                cur.execute(f"DROP SCHEMA IF EXISTS {sandbox['schema_name']} CASCADE")

            # Update status
            cur.execute(
                """
                UPDATE module_sandboxes
                SET status = 'inactive',
                    current_proposal_id = NULL
                WHERE module_id = %s
            """,
                (module_id,),
            )
            conn.commit()

            cur.close()
            conn.close()

            return {"success": True, "module_id": module_id, "status": "inactive"}

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return {"success": False, "error": str(e)}

    def detect_module_from_filepath(self, filepath: str) -> str:
        """
        Determine which module a file belongs to based on its path.

        Args:
            filepath: File path to analyze

        Returns:
            Module ID (e.g., 'bridge', 'improvements', 'platform')
        """
        module_paths = {
            "tools/starbase/": "starbase",
            "tools/improvements/": "improvements",
            "tools/consciousness/": "consciousness",
            "tools/admin/": "admin",
            "tools/backup_manager/": "admin",
            "tools/sandbox_manager/": "admin",
            "ai_bridge/": "ai_bridge",
            "tools/archie_chat/": "platform",
            "tools/code_editor/": "platform",
        }

        for path, module in module_paths.items():
            if path in filepath:
                return module

        return "platform"  # Default to full platform sandbox

    def update_module_sandbox_status(self, module_id: str, status: str, proposal_id: int = None) -> Dict:
        """Update the status of a module sandbox"""
        valid_statuses = ["inactive", "starting", "active", "testing", "stopping"]
        if status not in valid_statuses:
            return {
                "success": False,
                "error": f"Invalid status: {status}. Must be one of: {valid_statuses}",
            }

        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE module_sandboxes
            SET status = %s,
                current_proposal_id = COALESCE(%s, current_proposal_id),
                last_used_at = NOW()
            WHERE module_id = %s
            RETURNING *
        """,
            (status, proposal_id, module_id),
        )
        result = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return {"success": False, "error": f"Module sandbox not found: {module_id}"}

        return {"success": True, "sandbox": dict(result)}

    def run_module_sandbox_tests(self, module_id: str, test_suite: str = "default") -> Dict:
        """Run tests in a module sandbox"""
        # Get module sandbox
        sandbox_result = self.get_module_sandbox(module_id)
        if not sandbox_result["success"]:
            return sandbox_result

        sandbox = sandbox_result["sandbox"]

        if sandbox["status"] != "active":
            return {
                "success": False,
                "error": f'Module sandbox is not active: {sandbox["status"]}',
            }

        # Update status to testing
        self.update_module_sandbox_status(module_id, "testing")

        try:
            # Run tests
            if self.test_runner:
                if sandbox["sandbox_type"] == "schema":
                    test_result = self.test_runner.run_schema_tests(sandbox["schema_name"], test_suite)
                else:
                    test_result = self.test_runner.run_docker_tests(sandbox["container_name"], test_suite)

                # Update test counts
                conn = self.get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE module_sandboxes
                    SET total_tests_run = total_tests_run + %s,
                        tests_passed = tests_passed + %s,
                        tests_failed = tests_failed + %s,
                        last_test_at = NOW(),
                        status = 'active'
                    WHERE module_id = %s
                """,
                    (
                        test_result.get("total_tests", 0),
                        test_result.get("passed", 0),
                        test_result.get("failed", 0),
                        module_id,
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()

                return {
                    "success": True,
                    "module_id": module_id,
                    "test_suite": test_suite,
                    "results": test_result,
                }
            else:
                return {"success": False, "error": "Test runner not available"}

        except Exception as e:
            self.update_module_sandbox_status(module_id, "active")
            return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def create_sandbox_for_proposal(proposal_id: int, sandbox_type: str = None) -> Dict:
    """Quick function to create sandbox for a proposal"""
    manager = SandboxManager()
    return manager.create_sandbox(proposal_id, sandbox_type)


def run_sandbox_tests(sandbox_id: int, test_suite: str = "default") -> Dict:
    """Quick function to run tests in sandbox"""
    manager = SandboxManager()
    return manager.run_tests(sandbox_id, test_suite)


def cleanup_sandbox(sandbox_id: int) -> Dict:
    """Quick function to destroy sandbox"""
    manager = SandboxManager()
    return manager.destroy_sandbox(sandbox_id)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Sandbox Manager - Test Mode")
    print("=" * 60)

    manager = SandboxManager()

    # Test 1: Determine sandbox type
    print("\n1. SANDBOX TYPE DETERMINATION:")
    print("-" * 60)

    test_cases = [
        {"priority": "high", "expected": "docker_container"},
        {"complexity": "high", "expected": "docker_container"},
        {"category": "security", "expected": "docker_container"},
        {"category": "database", "expected": "docker_container"},
        {"priority": "low", "complexity": "low", "expected": "schema_separation"},
        {"category": "documentation", "expected": "schema_separation"},
    ]

    for case in test_cases:
        result = manager.determine_sandbox_type(**{k: v for k, v in case.items() if k != "expected"})
        status = "✓" if result == case["expected"] else "✗"
        print(f"{status} {case} → {result} (expected: {case['expected']})")

    print("\n✅ Sandbox Manager tests passed!")
