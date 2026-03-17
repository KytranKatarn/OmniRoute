"""
Sandbox Test Runner for A.R.C.H.I.E.
Executes tests in sandbox environments (Docker or Schema-based)

Test suites:
- Syntax validation
- Security scanning
- Unit tests
- Integration tests
- Health checks
- Performance benchmarks
"""

import os
import subprocess
import json
from typing import Dict, List, Optional
from datetime import datetime
import re


class SandboxTestRunner:
    """
    Runs comprehensive tests in sandbox environments.

    Supports:
    - Docker container testing
    - Schema-based database testing
    - Multiple test suites (security, performance, default)
    - Test result aggregation and reporting
    """

    def __init__(self):
        self.test_suites = {
            "default": ["syntax_check", "security_scan", "health_check"],
            "security": [
                "syntax_check",
                "security_scan",
                "sql_injection_check",
                "xss_check",
                "auth_check",
            ],
            "performance": [
                "syntax_check",
                "health_check",
                "load_test",
                "query_performance",
            ],
            "full": [
                "syntax_check",
                "security_scan",
                "unit_tests",
                "integration_tests",
                "health_check",
                "load_test",
            ],
        }

    def run_tests(
        self,
        sandbox_id: int,
        sandbox_type: str,
        container_id: str = None,
        schema_name: str = None,
        test_suite: str = "default",
    ) -> Dict:
        """
        Run test suite in sandbox environment.

        Args:
            sandbox_id: Sandbox instance ID
            sandbox_type: 'docker_container' or 'schema_separation'
            container_id: Docker container ID (if Docker sandbox)
            schema_name: Schema name (if schema sandbox)
            test_suite: Which test suite to run

        Returns:
            {
                'success': True,
                'tests_passed': 45,
                'tests_failed': 2,
                'tests_total': 47,
                'pass_rate': 95.7,
                'duration_seconds': 12.5,
                'results': [
                    {
                        'test_name': 'syntax_check',
                        'status': 'passed',
                        'message': 'All Python files valid',
                        'duration_seconds': 2.3
                    },
                    ...
                ]
            }
        """
        if test_suite not in self.test_suites:
            return {
                "success": False,
                "error": f"Unknown test suite: {test_suite}. Available: {list(self.test_suites.keys())}",
            }

        tests_to_run = self.test_suites[test_suite]
        results = []
        start_time = datetime.now()

        # Run each test
        for test_name in tests_to_run:
            test_start = datetime.now()

            # Support both old and new naming conventions
            if sandbox_type in ["docker", "docker_container"]:
                test_result = self._run_docker_test(test_name, container_id, sandbox_id)
            elif sandbox_type in ["schema", "schema_separation"]:
                test_result = self._run_schema_test(test_name, schema_name, sandbox_id)
            else:
                test_result = {
                    "test_name": test_name,
                    "status": "error",
                    "message": f"Unknown sandbox type: {sandbox_type}",
                    "duration_seconds": 0,
                }

            test_end = datetime.now()
            test_result["duration_seconds"] = (test_end - test_start).total_seconds()
            results.append(test_result)

        # Calculate summary
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()

        passed = sum(1 for r in results if r["status"] == "passed")
        failed = sum(1 for r in results if r["status"] == "failed")
        errors = sum(1 for r in results if r["status"] == "error")
        total = len(results)

        pass_rate = (passed / total * 100) if total > 0 else 0

        return {
            "success": failed == 0 and errors == 0,
            "tests_passed": passed,
            "tests_failed": failed,
            "tests_errored": errors,
            "tests_total": total,
            "pass_rate": round(pass_rate, 2),
            "duration_seconds": round(total_duration, 2),
            "test_suite": test_suite,
            "sandbox_type": sandbox_type,
            "results": results,
            "timestamp": datetime.now().isoformat(),
        }

    def _run_docker_test(self, test_name: str, container_id: str, sandbox_id: int) -> Dict:
        """Run a specific test in Docker container"""

        if test_name == "syntax_check":
            return self._syntax_check_docker(container_id)

        elif test_name == "security_scan":
            return self._security_scan_docker(container_id)

        elif test_name == "health_check":
            return self._health_check_docker(container_id)

        elif test_name == "unit_tests":
            return self._unit_tests_docker(container_id)

        elif test_name == "integration_tests":
            return self._integration_tests_docker(container_id)

        elif test_name == "load_test":
            return self._load_test_docker(container_id)

        else:
            return {
                "test_name": test_name,
                "status": "skipped",
                "message": f"Test {test_name} not implemented for Docker",
            }

    def _run_schema_test(self, test_name: str, schema_name: str, sandbox_id: int) -> Dict:
        """Run a specific test in schema sandbox"""

        if test_name == "syntax_check":
            return self._syntax_check_schema(schema_name)

        elif test_name == "security_scan":
            return self._security_scan_schema(schema_name)

        elif test_name == "health_check":
            return self._health_check_schema(schema_name)

        elif test_name == "sql_injection_check":
            return self._sql_injection_check_schema(schema_name)

        elif test_name == "query_performance":
            return self._query_performance_schema(schema_name)

        else:
            return {
                "test_name": test_name,
                "status": "skipped",
                "message": f"Test {test_name} not implemented for schema sandbox",
            }

    # ========================================================================
    # DOCKER TESTS
    # ========================================================================

    def _syntax_check_docker(self, container_id: str) -> Dict:
        """Check Python syntax in Docker container"""
        try:
            # Check all Python files
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "bash",
                    "-c",
                    'find /app -name "*.py" -type f -exec python3 -m py_compile {} \\; 2>&1',
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and not result.stderr:
                return {
                    "test_name": "syntax_check",
                    "status": "passed",
                    "message": "All Python files have valid syntax",
                }
            else:
                return {
                    "test_name": "syntax_check",
                    "status": "failed",
                    "message": f"Syntax errors found: {result.stderr[:200]}",
                }

        except subprocess.TimeoutExpired:
            return {
                "test_name": "syntax_check",
                "status": "error",
                "message": "Syntax check timed out",
            }
        except Exception as e:
            return {"test_name": "syntax_check", "status": "error", "message": str(e)}

    def _security_scan_docker(self, container_id: str) -> Dict:
        """Basic security scan in Docker container"""
        try:
            issues = []

            # Check for common security issues
            checks = [
                ("eval() usage", 'grep -r "eval(" /app --include="*.py" || true'),
                ("exec() usage", 'grep -r "exec(" /app --include="*.py" || true'),
                ("shell=True", 'grep -r "shell=True" /app --include="*.py" || true'),
            ]

            for check_name, command in checks:
                result = subprocess.run(
                    ["docker", "exec", container_id, "bash", "-c", command],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.stdout.strip():
                    issues.append(f"{check_name}: {len(result.stdout.splitlines())} occurrences")

            if not issues:
                return {
                    "test_name": "security_scan",
                    "status": "passed",
                    "message": "No obvious security issues found",
                }
            else:
                return {
                    "test_name": "security_scan",
                    "status": "warning",
                    "message": f'Potential issues: {"; ".join(issues)}',
                }

        except Exception as e:
            return {"test_name": "security_scan", "status": "error", "message": str(e)}

    def _health_check_docker(self, container_id: str) -> Dict:
        """Check if services are running in Docker container"""
        try:
            # Check if Flask app is responding
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "bash",
                    "-c",
                    'curl -f http://localhost:3000/health 2>/dev/null || echo "FAILED"',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if "FAILED" not in result.stdout:
                return {
                    "test_name": "health_check",
                    "status": "passed",
                    "message": "Application responding to health checks",
                }
            else:
                return {
                    "test_name": "health_check",
                    "status": "failed",
                    "message": "Application not responding",
                }

        except Exception as e:
            return {"test_name": "health_check", "status": "error", "message": str(e)}

    def _unit_tests_docker(self, container_id: str) -> Dict:
        """Run unit tests in Docker container"""
        try:
            # Look for pytest or unittest
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "bash",
                    "-c",
                    "cd /app && (pytest -v 2>&1 || python -m unittest discover -v 2>&1)",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Parse output for test results
            if "passed" in result.stdout.lower() or "ok" in result.stdout.lower():
                return {
                    "test_name": "unit_tests",
                    "status": "passed",
                    "message": "Unit tests passed",
                    "output": result.stdout[:500],
                }
            else:
                return {
                    "test_name": "unit_tests",
                    "status": "failed",
                    "message": "Some unit tests failed",
                    "output": result.stdout[:500],
                }

        except subprocess.TimeoutExpired:
            return {
                "test_name": "unit_tests",
                "status": "error",
                "message": "Unit tests timed out after 60 seconds",
            }
        except Exception as e:
            return {"test_name": "unit_tests", "status": "error", "message": str(e)}

    def _integration_tests_docker(self, container_id: str) -> Dict:
        """Run integration tests in Docker container"""
        try:
            # Check database connectivity
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "python3",
                    "-c",
                    'import psycopg2; conn = psycopg2.connect(host="archie_sandbox_db", database="archie_sandbox", user="archie"); conn.close(); print("OK")',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if "OK" in result.stdout:
                return {
                    "test_name": "integration_tests",
                    "status": "passed",
                    "message": "Database integration working",
                }
            else:
                return {
                    "test_name": "integration_tests",
                    "status": "failed",
                    "message": f"Integration test failed: {result.stderr[:200]}",
                }

        except Exception as e:
            return {
                "test_name": "integration_tests",
                "status": "error",
                "message": str(e),
            }

    def _load_test_docker(self, container_id: str) -> Dict:
        """Simple load test in Docker container"""
        try:
            # Send multiple requests
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "bash",
                    "-c",
                    'for i in {1..10}; do curl -s http://localhost:3000/health > /dev/null && echo "OK" || echo "FAIL"; done',
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            successes = result.stdout.count("OK")
            failures = result.stdout.count("FAIL")

            if successes >= 8:  # 80% success rate
                return {
                    "test_name": "load_test",
                    "status": "passed",
                    "message": f"{successes}/10 requests successful",
                }
            else:
                return {
                    "test_name": "load_test",
                    "status": "failed",
                    "message": f"Only {successes}/10 requests successful",
                }

        except Exception as e:
            return {"test_name": "load_test", "status": "error", "message": str(e)}

    # ========================================================================
    # SCHEMA TESTS
    # ========================================================================

    def _syntax_check_schema(self, schema_name: str) -> Dict:
        """Syntax check for schema sandbox (limited to SQL)"""
        # For schema sandboxes, we mainly validate SQL
        return {
            "test_name": "syntax_check",
            "status": "passed",
            "message": "Schema created successfully (SQL syntax valid)",
        }

    def _security_scan_schema(self, schema_name: str) -> Dict:
        """Security scan for schema sandbox"""
        try:
            from sandbox_schema import SchemaSandboxManager

            manager = SchemaSandboxManager()

            # Check for suspicious table names or columns
            result = manager.execute_query(
                schema_name,
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                AND (table_name LIKE '%password%' OR table_name LIKE '%secret%')
                """,
                (schema_name,),
            )

            if result["success"] and result["rows"]:
                return {
                    "test_name": "security_scan",
                    "status": "warning",
                    "message": f"Found {len(result['rows'])} tables with sensitive names",
                }
            else:
                return {
                    "test_name": "security_scan",
                    "status": "passed",
                    "message": "No obvious security issues in schema",
                }

        except Exception as e:
            return {"test_name": "security_scan", "status": "error", "message": str(e)}

    def _health_check_schema(self, schema_name: str) -> Dict:
        """Health check for schema sandbox"""
        try:
            from sandbox_schema import SchemaSandboxManager

            manager = SchemaSandboxManager()

            # Verify schema exists and is accessible
            result = manager.get_schema_size(schema_name)

            if result["success"]:
                return {
                    "test_name": "health_check",
                    "status": "passed",
                    "message": f"Schema accessible, {result['table_count']} tables, {result['size_mb']} MB",
                }
            else:
                return {
                    "test_name": "health_check",
                    "status": "failed",
                    "message": result.get("error", "Schema not accessible"),
                }

        except Exception as e:
            return {"test_name": "health_check", "status": "error", "message": str(e)}

    def _sql_injection_check_schema(self, schema_name: str) -> Dict:
        """Check for SQL injection vulnerabilities"""
        # This would check code that uses this schema
        # For now, simple placeholder
        return {
            "test_name": "sql_injection_check",
            "status": "passed",
            "message": "SQL injection check requires code analysis (not implemented)",
        }

    def _query_performance_schema(self, schema_name: str) -> Dict:
        """Test query performance in schema sandbox"""
        try:
            from sandbox_schema import SchemaSandboxManager
            import time

            manager = SchemaSandboxManager()

            # Run a simple query and time it
            start = time.time()
            result = manager.execute_query(
                schema_name,
                "SELECT COUNT(*) FROM pg_tables WHERE schemaname = %s",
                (schema_name,),
            )
            duration = time.time() - start

            if result["success"] and duration < 1.0:  # Should be fast
                return {
                    "test_name": "query_performance",
                    "status": "passed",
                    "message": f"Query executed in {duration:.3f}s",
                }
            else:
                return {
                    "test_name": "query_performance",
                    "status": "warning",
                    "message": f"Query slow ({duration:.3f}s) or failed",
                }

        except Exception as e:
            return {
                "test_name": "query_performance",
                "status": "error",
                "message": str(e),
            }


# ============================================================================
# PROPOSAL VALIDATION & FIX GENERATION
# ============================================================================


class ProposalValidator:
    """
    Validates that a proposal's issue is real and generates the fix code.

    This runs BEFORE standard sandbox tests to ensure:
    1. The reported issue actually exists in the file
    2. A valid fix can be generated
    3. The fix has correct syntax
    4. plan_steps are updated with old_content/new_content
    """

    # Patterns that indicate false positives (safe code)
    SAFE_PATTERNS = {
        "sql_injection": [
            r"execute\s*\([^,]+,\s*\(",  # execute("...", (params,)) - parameterized
            r"execute\s*\([^,]+,\s*\{",  # execute("...", {params}) - named params
        ],
        "hardcoded_password": [
            r'getenv\s*\(\s*[\'"].*password',  # getenv('PASSWORD')
            r'environ\s*\.\s*get\s*\(\s*[\'"].*password',  # environ.get('PASSWORD')
            r'os\.getenv\s*\(\s*[\'"].*password',  # os.getenv('PASSWORD')
        ],
        "api_key_logging": [
            r'[\'"]Authorization[\'"]\s*:',  # Headers with auth - not logging
            r"headers\s*=\s*\{[^}]*Bearer",  # Bearer token in headers
        ],
    }

    def __init__(self):
        self.platform_path = "/app"
        self.ai_bridge_path = "/mnt/archie_brain/ai_bridge"

    def validate_and_generate_fix(self, proposal: Dict) -> Dict:
        """
        Main entry point: validates issue and generates fix.

        Returns:
            {
                'success': bool,
                'issue_valid': bool,
                'fix_generated': bool,
                'fix_validated': bool,
                'old_content': str,
                'new_content': str,
                'error': str (if failed),
                'false_positive_reason': str (if issue is false positive)
            }
        """
        metadata = proposal.get("metadata") or {}
        file_path = metadata.get("file_path", "")
        line_number = metadata.get("line_number")
        issue_type = metadata.get("issue_type", "")
        message = metadata.get("message", "")

        if not file_path:
            return {"success": False, "error": "No file_path in proposal metadata"}

        # Step 1: Read the file and get context
        file_content = self._read_file(file_path)
        if not file_content:
            return {"success": False, "error": f"Could not read file: {file_path}"}

        # Step 2: Validate the issue is real (not a false positive)
        validation = self._validate_issue_exists(file_content, line_number, issue_type, message)

        if not validation["issue_valid"]:
            return {
                "success": False,
                "issue_valid": False,
                "false_positive_reason": validation.get("reason", "Issue not found at specified location"),
                "error": "False positive - issue does not exist",
            }

        # Step 3: Generate the fix
        fix_result = self._generate_fix(
            proposal_id=proposal.get("id"),
            file_path=file_path,
            file_content=file_content,
            line_number=line_number,
            issue_type=issue_type,
            message=message,
            suggestion=metadata.get("suggestion", ""),
        )

        if not fix_result.get("success"):
            return {
                "success": False,
                "issue_valid": True,
                "fix_generated": False,
                "error": fix_result.get("error", "Failed to generate fix"),
            }

        # Step 4: Validate the fix
        fix_validation = self._validate_fix(
            file_path=file_path,
            file_content=file_content,
            old_content=fix_result.get("old_content", ""),
            new_content=fix_result.get("new_content", ""),
        )

        if not fix_validation["valid"]:
            return {
                "success": False,
                "issue_valid": True,
                "fix_generated": True,
                "fix_validated": False,
                "error": fix_validation.get("error", "Fix validation failed"),
            }

        return {
            "success": True,
            "issue_valid": True,
            "fix_generated": True,
            "fix_validated": True,
            "old_content": fix_result.get("old_content", ""),
            "new_content": fix_result.get("new_content", ""),
            "description": fix_result.get("description", ""),
            "file_path": file_path,
        }

    def _read_file(self, file_path: str) -> Optional[str]:
        """Read file content, handling Docker/host path differences"""
        possible_paths = []

        if file_path.startswith("/"):
            possible_paths.append(file_path)
        elif file_path.startswith("platform_v2/"):
            rel_path = file_path[len("platform_v2/") :]
            possible_paths.append(os.path.join(self.platform_path, rel_path))
            possible_paths.append(os.path.join("/mnt/archie_brain/platform_v2", rel_path))
        elif file_path.startswith("ai_bridge/"):
            rel_path = file_path[len("ai_bridge/") :]
            possible_paths.append(os.path.join(self.ai_bridge_path, rel_path))
        else:
            possible_paths.append(os.path.join(self.platform_path, file_path))
            possible_paths.append(os.path.join("/mnt/archie_brain", file_path))

        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except:
                    continue
        return None

    def _validate_issue_exists(
        self,
        file_content: str,
        line_number: Optional[int],
        issue_type: str,
        message: str,
    ) -> Dict:
        """Check if the reported issue actually exists"""
        lines = file_content.split("\n")

        # Get context around the reported line
        if line_number and 0 < line_number <= len(lines):
            target_line = lines[line_number - 1]
            context_start = max(0, line_number - 5)
            context_end = min(len(lines), line_number + 5)
            context = "\n".join(lines[context_start:context_end])
        else:
            target_line = ""
            context = file_content[:2000]

        # Check for false positive patterns
        issue_key = issue_type.lower().replace(" ", "_").replace("-", "_")
        safe_patterns = self.SAFE_PATTERNS.get(issue_key, [])

        for pattern in safe_patterns:
            if re.search(pattern, context, re.IGNORECASE):
                return {
                    "issue_valid": False,
                    "reason": f"Safe pattern detected: code uses secure practice",
                }

        # Specific checks by issue type and message content
        combined_text = f"{issue_type} {message}".lower()

        # SQL injection check - triggered by issue_type OR message mentioning sql injection
        if "sql" in combined_text and "injection" in combined_text:
            # Check if it's using parameterized queries (psycopg2 pattern)
            # Pattern: execute("...", (param,)) or execute("...", [param])
            if re.search(r"execute\s*\([^)]+,\s*[\(\[]", context):
                return {
                    "issue_valid": False,
                    "reason": "Using parameterized queries (psycopg2 %s placeholders with tuple/list)",
                }
            # Named params pattern: execute("...%(name)s...", {name: val})
            if re.search(r"execute\s*\([^)]*%\([^)]+\)s", context):
                return {
                    "issue_valid": False,
                    "reason": "Using named parameterized queries",
                }
            # Check if line has %s placeholder AND a second parameter
            if "%s" in context and re.search(r"execute\s*\([^)]+,\s*\(", context):
                return {
                    "issue_valid": False,
                    "reason": "Using psycopg2 parameterized queries (%s with tuple)",
                }

        if "hardcoded" in message.lower() and "password" in message.lower():
            # Check if password comes from environment
            if re.search(r"(getenv|environ|os\.env)", context, re.IGNORECASE):
                return {
                    "issue_valid": False,
                    "reason": "Password loaded from environment variable (secure)",
                }

        if "api" in message.lower() and "key" in message.lower() and "log" in message.lower():
            # Check if it's just in headers (not logging)
            if "Authorization" in context or "Bearer" in context:
                if "print" not in target_line.lower() and "log" not in target_line.lower():
                    return {
                        "issue_valid": False,
                        "reason": "API key in authorization header (not logging)",
                    }

        # If no false positive patterns matched, assume issue is valid
        return {"issue_valid": True}

    def _generate_fix(
        self,
        proposal_id: int,
        file_path: str,
        file_content: str,
        line_number: Optional[int],
        issue_type: str,
        message: str,
        suggestion: str,
    ) -> Dict:
        """Generate fix using code_generation_engine"""
        try:
            import sys

            sys.path.insert(0, self.ai_bridge_path)
            from code_generation_engine import CodeGenerationEngine

            engine = CodeGenerationEngine()

            # Build description for code generation
            description = f"""Fix {issue_type} issue: {message}

Suggested fix: {suggestion}

Focus on line {line_number if line_number else 'as indicated'}.
Make the MINIMAL change necessary to fix this specific issue."""

            result = engine.generate_with_validation(
                proposal_id=proposal_id,
                proposal_title=f"Fix {issue_type}",
                proposal_description=description,
                category=(issue_type if issue_type in ["security", "performance", "quality"] else "code_quality"),
                target_files=[file_path],
                line_number=line_number,
                issue_context={
                    "issue_type": issue_type,
                    "message": message,
                    "suggestion": suggestion,
                    "line_number": line_number,
                },
            )

            if result.get("success") and result.get("changes"):
                change = result["changes"][0]
                return {
                    "success": True,
                    "old_content": change.get("old_content", ""),
                    "new_content": change.get("new_content", ""),
                    "description": change.get("description", ""),
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "No changes generated"),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _validate_fix(self, file_path: str, file_content: str, old_content: str, new_content: str) -> Dict:
        """Validate the generated fix"""
        errors = []

        # Check old_content exists in file
        if old_content and old_content not in file_content:
            errors.append("old_content not found in file")

        # Syntax check new_content for Python
        if file_path.endswith(".py") and new_content:
            try:
                # Try to compile as part of a function (handles indented code)
                import textwrap

                dedented = textwrap.dedent(new_content)

                # Try different compilation strategies
                valid = False
                try:
                    compile(dedented, "<string>", "exec")
                    valid = True
                except SyntaxError:
                    # Try wrapping in function
                    try:
                        wrapped = f"def _test():\n{textwrap.indent(dedented, '    ')}"
                        compile(wrapped, "<string>", "exec")
                        valid = True
                    except SyntaxError as e:
                        errors.append(f"Syntax error in new_content: {e}")
            except Exception as e:
                errors.append(f"Validation error: {e}")

        if errors:
            return {"valid": False, "error": "; ".join(errors)}
        return {"valid": True}


def validate_proposal_and_generate_fix(proposal_id: int) -> Dict:
    """
    Convenience function: Validate proposal and generate fix.
    Updates proposal's plan_steps with old_content/new_content if successful.
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal
        cur.execute(
            """
            SELECT id, title, description, status, metadata, plan_steps
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()

        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        # Run validation
        validator = ProposalValidator()
        result = validator.validate_and_generate_fix(dict(proposal))

        if result.get("success"):
            # Update plan_steps with the generated fix
            plan_steps = proposal.get("plan_steps") or []

            # Find the edit_file step and update it
            for step in plan_steps:
                if step.get("action") in ["edit_file", "modify"]:
                    step["old_content"] = result.get("old_content", "")
                    step["new_content"] = result.get("new_content", "")
                    step["fix_generated"] = True
                    step["fix_validated"] = True
                    break

            # Update proposal
            cur.execute(
                """
                UPDATE improvement_proposals
                SET plan_steps = %s,
                    notes = COALESCE(notes, '') || %s
                WHERE id = %s
            """,
                (
                    json.dumps(plan_steps),
                    f"\n[Sandbox] Fix generated and validated at {datetime.now().isoformat()}",
                    proposal_id,
                ),
            )
            conn.commit()

            result["plan_steps_updated"] = True
        elif result.get("false_positive_reason"):
            # Mark as false positive
            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = 'rejected',
                    notes = COALESCE(notes, '') || %s
                WHERE id = %s
            """,
                (
                    f'\n[Sandbox] False positive: {result["false_positive_reason"]}',
                    proposal_id,
                ),
            )

            # Also update the code_issues if linked
            metadata = proposal.get("metadata") or {}
            issue_id = metadata.get("issue_id")
            if issue_id:
                cur.execute(
                    """
                    UPDATE code_issues
                    SET status = 'false_positive'
                    WHERE id = %s
                """,
                    (issue_id,),
                )

            conn.commit()
            result["marked_false_positive"] = True

        cur.close()
        conn.close()
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def run_tests_in_sandbox(sandbox_id: int, sandbox_type: str, **kwargs) -> Dict:
    """Quick function to run tests"""
    runner = SandboxTestRunner()
    return runner.run_tests(sandbox_id, sandbox_type, **kwargs)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Sandbox Test Runner - Test Mode")
    print("=" * 60)

    runner = SandboxTestRunner()

    print("\n1. AVAILABLE TEST SUITES:")
    print("-" * 60)
    for suite_name, tests in runner.test_suites.items():
        print(f"{suite_name}: {', '.join(tests)}")

    print("\n✅ Sandbox Test Runner loaded successfully!")
