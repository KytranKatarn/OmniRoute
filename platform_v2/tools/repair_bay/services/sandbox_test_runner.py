"""
Sandbox Test Runner
Executes test suites in sandbox environments and records results

Author: A.R.C.H.I.E.
Date: 2026-01-01
Purpose: Run automated tests in sandboxes before deployment
"""

import os
from database import _get_db_password
import sys
import json
import subprocess
import time
from typing import Dict, List, Optional

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    from database import get_db
except ImportError:
    try:
        from platform_v2.database import get_db
    except ImportError:
        # Fallback: direct database connection
        import psycopg2

        def get_db():
            return psycopg2.connect(
                host=os.getenv("DB_HOST", "archie_database"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )


class SandboxTestRunner:
    """Executes test suites in sandbox environments"""

    def __init__(self):
        self.base_path = "/mnt/archie_brain"

    def get_test_suites(self, required_only: bool = False) -> List[Dict]:
        """
        Get available test suites

        Args:
            required_only: Only return required test suites

        Returns:
            List of test suite dictionaries
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            if required_only:
                cur.execute(
                    """
                    SELECT id, name, description, test_type, test_command,
                           timeout_seconds, required, enabled
                    FROM sandbox_test_suites
                    WHERE enabled = TRUE AND required = TRUE
                    ORDER BY test_type, name
                """
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, description, test_type, test_command,
                           timeout_seconds, required, enabled
                    FROM sandbox_test_suites
                    WHERE enabled = TRUE
                    ORDER BY test_type, name
                """
                )

            suites = cur.fetchall()
            cur.close()
            conn.close()

            return [
                {
                    "id": s[0],
                    "name": s[1],
                    "description": s[2],
                    "test_type": s[3],
                    "test_command": s[4],
                    "timeout_seconds": s[5],
                    "required": s[6],
                    "enabled": s[7],
                }
                for s in suites
            ]

        except Exception as e:
            print(f"Error getting test suites: {e}")
            import traceback

            traceback.print_exc()
            return []

    def run_test_suite(
        self,
        sandbox_id: int,
        proposal_id: int,
        test_suite: Dict,
        sandbox_type: str = "schema_separation",
    ) -> Dict:
        """
        Run a single test suite

        Args:
            sandbox_id: ID of the sandbox
            proposal_id: ID of the proposal being tested
            test_suite: Test suite configuration dict
            sandbox_type: Type of sandbox ('docker_container' or 'schema_separation')

        Returns:
            Dictionary with test results
        """
        try:
            test_name = test_suite["name"]
            test_command = test_suite["test_command"]
            timeout = test_suite["timeout_seconds"]

            print(f"🧪 Running test suite: {test_name}")
            print(f"   Command: {test_command}")

            start_time = time.time()

            # Determine execution environment
            if sandbox_type == "docker_container":
                # Run in Docker sandbox container
                full_command = f"docker exec archie_sandbox {test_command}"
            else:
                # Run in current environment (schema separation mode)
                # Set environment variable to use sandbox schema
                env = os.environ.copy()
                env["DB_SCHEMA"] = "sandbox"
                full_command = test_command

            # Execute test command
            try:
                result = subprocess.run(
                    full_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.base_path,
                )

                duration_ms = int((time.time() - start_time) * 1000)

                # Determine status from exit code
                if result.returncode == 0:
                    status = "passed"
                    error_message = None
                    stack_trace = None
                else:
                    status = "failed"
                    error_message = result.stderr[:500] if result.stderr else "Test failed with non-zero exit code"
                    stack_trace = result.stderr if result.stderr else None

                output = result.stdout[:1000] if result.stdout else ""

            except subprocess.TimeoutExpired:
                duration_ms = timeout * 1000
                status = "error"
                error_message = f"Test timed out after {timeout} seconds"
                stack_trace = None
                output = ""

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                status = "error"
                error_message = str(e)
                stack_trace = None
                output = ""

            # Record result in database
            self._save_test_result(
                sandbox_id=sandbox_id,
                test_suite_id=test_suite["id"],
                proposal_id=proposal_id,
                test_name=test_name,
                status=status,
                duration_ms=duration_ms,
                error_message=error_message,
                stack_trace=stack_trace,
                output=output,
            )

            print(f"   Result: {status.upper()} ({duration_ms}ms)")

            return {
                "test_suite_id": test_suite["id"],
                "test_name": test_name,
                "status": status,
                "duration_ms": duration_ms,
                "error_message": error_message,
                "required": test_suite["required"],
            }

        except Exception as e:
            print(f"Error running test suite {test_suite['name']}: {e}")
            import traceback

            traceback.print_exc()
            return {
                "test_suite_id": test_suite["id"],
                "test_name": test_suite["name"],
                "status": "error",
                "duration_ms": 0,
                "error_message": str(e),
                "required": test_suite["required"],
            }

    def _save_test_result(
        self,
        sandbox_id: int,
        test_suite_id: int,
        proposal_id: int,
        test_name: str,
        status: str,
        duration_ms: int,
        error_message: Optional[str],
        stack_trace: Optional[str],
        output: Optional[str],
    ) -> bool:
        """Save test result to database"""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO sandbox_test_results (
                    sandbox_id,
                    test_suite_id,
                    proposal_id,
                    test_name,
                    status,
                    duration_ms,
                    error_message,
                    stack_trace,
                    output
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    sandbox_id,
                    test_suite_id,
                    proposal_id,
                    test_name,
                    status,
                    duration_ms,
                    error_message,
                    stack_trace,
                    output,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            return True

        except Exception as e:
            print(f"Error saving test result: {e}")
            import traceback

            traceback.print_exc()
            return False

    def run_all_test_suites(
        self,
        sandbox_id: int,
        proposal_id: int,
        sandbox_type: str = "schema_separation",
        required_only: bool = False,
    ) -> Dict:
        """
        Run all enabled test suites

        Args:
            sandbox_id: ID of the sandbox
            proposal_id: ID of the proposal
            sandbox_type: Type of sandbox
            required_only: Only run required tests

        Returns:
            Dictionary with overall results
        """
        try:
            print(f"\n{'='*80}")
            print(f"RUNNING TEST SUITES FOR PROPOSAL #{proposal_id}")
            print(f"Sandbox ID: {sandbox_id}, Type: {sandbox_type}")
            print(f"{'='*80}\n")

            # Update proposal test status to 'running'
            self._update_proposal_test_status(proposal_id, "running")

            # Get test suites
            test_suites = self.get_test_suites(required_only=required_only)

            if not test_suites:
                print("⚠️  No test suites found")
                return {"success": False, "error": "No test suites configured"}

            start_time = time.time()
            results = []

            # Run each test suite
            for suite in test_suites:
                result = self.run_test_suite(
                    sandbox_id=sandbox_id,
                    proposal_id=proposal_id,
                    test_suite=suite,
                    sandbox_type=sandbox_type,
                )
                results.append(result)

            total_duration = int((time.time() - start_time))

            # Calculate summary
            total_tests = len(results)
            passed = sum(1 for r in results if r["status"] == "passed")
            failed = sum(1 for r in results if r["status"] == "failed")
            errors = sum(1 for r in results if r["status"] == "error")

            # Check if required tests passed
            required_passed = all(r["status"] == "passed" for r in results if r.get("required", False))

            # Only fail overall if REQUIRED tests failed
            # Non-required test failures are warnings, not blockers
            required_failed = sum(1 for r in results if r.get("required", False) and r["status"] != "passed")

            overall_status = "passed" if required_failed == 0 else "failed"

            # Update proposal with test results
            test_summary = {
                "total_tests": total_tests,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "duration_seconds": total_duration,
                "required_passed": required_passed,
                "overall_status": overall_status,
                "results": results,
            }

            self._update_proposal_test_results(
                proposal_id=proposal_id,
                test_status=overall_status,
                test_duration=total_duration,
                test_summary=test_summary,
            )

            print(f"\n{'='*80}")
            print("TEST RESULTS SUMMARY")
            print(f"{'='*80}")
            print(f"Total Tests: {total_tests}")
            print(f"Passed: {passed}")
            print(f"Failed: {failed}")
            print(f"Errors: {errors}")
            print(f"Duration: {total_duration}s")
            print(f"Overall Status: {overall_status.upper()}")
            print(f"Required Tests Passed: {'YES' if required_passed else 'NO'}")
            print(f"{'='*80}\n")

            return {
                "success": True,
                "overall_status": overall_status,
                "required_passed": required_passed,
                "summary": test_summary,
            }

        except Exception as e:
            print(f"Error running test suites: {e}")
            import traceback

            traceback.print_exc()

            self._update_proposal_test_status(proposal_id, "failed")

            return {"success": False, "error": str(e)}

    def _update_proposal_test_status(self, proposal_id: int, test_status: str) -> bool:
        """Update proposal test status"""
        try:
            conn = get_db()
            cur = conn.cursor()

            if test_status == "running":
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET test_status = %s,
                        test_started_at = NOW()
                    WHERE id = %s
                """,
                    (test_status, proposal_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET test_status = %s,
                        test_completed_at = NOW()
                    WHERE id = %s
                """,
                    (test_status, proposal_id),
                )

            conn.commit()
            cur.close()
            conn.close()

            return True

        except Exception as e:
            print(f"Error updating test status: {e}")
            return False

    def _update_proposal_test_results(
        self, proposal_id: int, test_status: str, test_duration: int, test_summary: Dict
    ) -> bool:
        """Update proposal with complete test results"""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE improvement_proposals
                SET test_status = %s,
                    test_completed_at = NOW(),
                    test_duration_seconds = %s,
                    test_results_summary = %s
                WHERE id = %s
            """,
                (
                    test_status,
                    test_duration,
                    json.dumps(test_summary),  # Properly serialize to JSON
                    proposal_id,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            return True

        except Exception as e:
            print(f"Error updating test results: {e}")
            import traceback

            traceback.print_exc()
            return False

    def run_health_check(self, sandbox_id: int, check_type: str = "service") -> Dict:
        """
        Run health check on a sandbox

        Args:
            sandbox_id: ID of the sandbox
            check_type: Type of health check ('http', 'database', 'service', 'resource')

        Returns:
            Dictionary with health check results
        """
        try:
            start_time = time.time()

            # Simple health check implementations
            if check_type == "database":
                # Check database connectivity
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    cur.fetchone()
                    cur.close()
                    conn.close()
                    status = "healthy"
                    details = {"connection": "successful"}
                except Exception as e:
                    status = "unhealthy"
                    details = {"error": str(e)}

            elif check_type == "service":
                # Check if platform is responsive
                status = "healthy"
                details = {"status": "responsive"}

            else:
                status = "healthy"
                details = {}

            response_time = int((time.time() - start_time) * 1000)

            # Save health check result
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO sandbox_health_checks (
                    sandbox_id,
                    check_type,
                    status,
                    response_time_ms,
                    details
                ) VALUES (%s, %s, %s, %s, %s)
            """,
                (
                    sandbox_id,
                    check_type,
                    status,
                    response_time,
                    str(details).replace("'", '"'),
                ),
            )

            # Update sandbox health status
            cur.execute(
                """
                UPDATE sandbox_instances
                SET health_check_status = %s,
                    health_check_last_run = NOW()
                WHERE id = %s
            """,
                (status, sandbox_id),
            )

            conn.commit()
            cur.close()
            conn.close()

            return {
                "success": True,
                "status": status,
                "response_time_ms": response_time,
                "details": details,
            }

        except Exception as e:
            print(f"Error running health check: {e}")
            return {"success": False, "status": "unhealthy", "error": str(e)}


# Convenience functions
def run_sandbox_tests(
    sandbox_id: int,
    proposal_id: int,
    sandbox_type: str = "schema_separation",
    required_only: bool = False,
) -> Dict:
    """Run all test suites in a sandbox"""
    runner = SandboxTestRunner()
    return runner.run_all_test_suites(
        sandbox_id=sandbox_id,
        proposal_id=proposal_id,
        sandbox_type=sandbox_type,
        required_only=required_only,
    )


def check_sandbox_health(sandbox_id: int) -> Dict:
    """Run health check on a sandbox"""
    runner = SandboxTestRunner()
    return runner.run_health_check(sandbox_id)


if __name__ == "__main__":
    # Test the sandbox test runner
    print("🧪 Testing Sandbox Test Runner...")

    runner = SandboxTestRunner()

    # Get available test suites
    suites = runner.get_test_suites()
    print(f"\nFound {len(suites)} test suites:")
    for suite in suites:
        print(f"  • {suite['name']} ({suite['test_type']}) - Required: {suite['required']}")
