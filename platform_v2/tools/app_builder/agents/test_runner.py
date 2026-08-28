"""
Test Runner Agent
Executes test suites and parses results for backend and frontend
Part of A.R.C.H.I.E. App Builder - Week 5: Testing Framework
"""

import os
import json
import re
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Any
from datetime import datetime, timezone
import asyncio


class TestRunner:
    """
    Executes tests and parses results for pytest (backend) and Jest (frontend)
    """

    def __init__(self, project_id: int, project_path: str, project_plan: Optional[Dict] = None):
        """
        Initialize Test Runner

        Args:
            project_id: Project database ID
            project_path: Path to project directory
            project_plan: Optional project plan details
        """
        self.project_id = project_id
        self.project_path = project_path
        self.project_plan = project_plan or {}
        self.test_results = {}

        # Paths
        self.backend_path = os.path.join(project_path, "backend")
        self.frontend_path = os.path.join(project_path, "frontend")

    async def run_tests(
        self,
        test_backend: bool = True,
        test_frontend: bool = True,
        test_type: str = "all",
    ) -> Dict[str, Any]:
        """
        Run all tests and collect results

        Args:
            test_backend: Run backend tests
            test_frontend: Run frontend tests
            test_type: Type of tests to run ('all', 'unit', 'integration')

        Returns:
            Dictionary with test results
        """
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "backend": None,
            "frontend": None,
            "overall_success": True,
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "skipped_tests": 0,
            "coverage": {},
        }

        # Run backend tests
        if test_backend and os.path.exists(self.backend_path):
            backend_result = await self._run_backend_tests(test_type)
            results["backend"] = backend_result
            results["overall_success"] = results["overall_success"] and backend_result["success"]
            results["total_tests"] += backend_result["total"]
            results["passed_tests"] += backend_result["passed"]
            results["failed_tests"] += backend_result["failed"]
            results["skipped_tests"] += backend_result["skipped"]
            results["coverage"]["backend"] = backend_result.get("coverage", {})

        # Run frontend tests
        if test_frontend and os.path.exists(self.frontend_path):
            frontend_result = await self._run_frontend_tests(test_type)
            results["frontend"] = frontend_result
            results["overall_success"] = results["overall_success"] and frontend_result["success"]
            results["total_tests"] += frontend_result["total"]
            results["passed_tests"] += frontend_result["passed"]
            results["failed_tests"] += frontend_result["failed"]
            results["skipped_tests"] += frontend_result["skipped"]
            results["coverage"]["frontend"] = frontend_result.get("coverage", {})

        # Calculate success rate
        if results["total_tests"] > 0:
            results["success_rate"] = (results["passed_tests"] / results["total_tests"]) * 100
        else:
            results["success_rate"] = 0

        self.test_results = results
        return results

    # ============================================================================
    # BACKEND TEST EXECUTION (PYTEST)
    # ============================================================================

    async def _run_backend_tests(self, test_type: str = "all") -> Dict[str, Any]:
        """
        Run backend tests using pytest

        Args:
            test_type: Type of tests ('all', 'unit', 'integration', 'auth', 'api')

        Returns:
            Dictionary with test results
        """
        result = {
            "success": False,
            "framework": "pytest",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration": 0,
            "failures": [],
            "coverage": {},
            "output": "",
            "error": None,
        }

        try:
            # Build pytest command
            cmd = ["pytest"]

            # Add test type markers
            if test_type != "all":
                cmd.extend(["-m", test_type])

            # Add output options
            cmd.extend(
                [
                    "-v",  # Verbose
                    "--tb=short",  # Short traceback
                    "--junitxml=test-results.xml",  # XML output for parsing
                    "--cov=.",  # Coverage
                    "--cov-report=json",  # JSON coverage report
                    "--cov-report=term-missing",  # Terminal coverage report
                ]
            )

            # Run tests
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.backend_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            # Store output
            result["output"] = stdout.decode("utf-8")
            if stderr:
                result["error"] = stderr.decode("utf-8")

            # Parse test results from XML
            xml_path = os.path.join(self.backend_path, "test-results.xml")
            if os.path.exists(xml_path):
                xml_results = self._parse_pytest_xml(xml_path)
                result.update(xml_results)

            # Parse coverage from JSON
            coverage_path = os.path.join(self.backend_path, "coverage.json")
            if os.path.exists(coverage_path):
                coverage_results = self._parse_coverage_json(coverage_path)
                result["coverage"] = coverage_results

            # Parse text output for additional info
            text_results = self._parse_pytest_output(result["output"])
            result["duration"] = text_results.get("duration", 0)

            # Success if no failures
            result["success"] = result["failed"] == 0 and process.returncode == 0

        except FileNotFoundError:
            result["error"] = "pytest not found. Make sure it is installed (pip install pytest)"
        except Exception as e:
            result["error"] = f"Error running backend tests: {str(e)}"

        return result

    def _parse_pytest_xml(self, xml_path: str) -> Dict[str, Any]:
        """Parse pytest JUnit XML output"""
        result = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "failures": []}

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Get test suite statistics
            testsuite = root.find(".//testsuite")
            if testsuite is not None:
                result["total"] = int(testsuite.get("tests", 0))
                result["failed"] = int(testsuite.get("failures", 0)) + int(testsuite.get("errors", 0))
                result["skipped"] = int(testsuite.get("skipped", 0))
                result["passed"] = result["total"] - result["failed"] - result["skipped"]

            # Get failure details
            for testcase in root.findall(".//testcase"):
                failure = testcase.find("failure")
                error = testcase.find("error")

                if failure is not None or error is not None:
                    failure_info = {
                        "test_name": testcase.get("name"),
                        "class_name": testcase.get("classname"),
                        "file": testcase.get("file"),
                        "line": testcase.get("line"),
                        "message": (failure.get("message") if failure is not None else error.get("message")),
                        "details": failure.text if failure is not None else error.text,
                    }
                    result["failures"].append(failure_info)

        except Exception as e:
            print(f"Error parsing pytest XML: {e}")

        return result

    def _parse_pytest_output(self, output: str) -> Dict[str, Any]:
        """Parse pytest text output for additional information"""
        result = {"duration": 0, "warnings": []}

        # Extract duration
        duration_match = re.search(r"(\d+\.\d+)s", output)
        if duration_match:
            result["duration"] = float(duration_match.group(1))

        # Extract warnings
        warning_matches = re.findall(r"WARNING: (.+)", output)
        result["warnings"] = warning_matches

        return result

    def _parse_coverage_json(self, coverage_path: str) -> Dict[str, Any]:
        """Parse coverage.json from pytest-cov"""
        coverage_result = {
            "total_statements": 0,
            "covered_statements": 0,
            "missing_statements": 0,
            "coverage_percent": 0,
            "files": {},
        }

        try:
            with open(coverage_path, "r") as f:
                coverage_data = json.load(f)

            # Get totals
            totals = coverage_data.get("totals", {})
            coverage_result["total_statements"] = totals.get("num_statements", 0)
            coverage_result["covered_statements"] = totals.get("covered_lines", 0)
            coverage_result["missing_statements"] = totals.get("missing_lines", 0)
            coverage_result["coverage_percent"] = round(totals.get("percent_covered", 0), 2)

            # Get file-level coverage
            files = coverage_data.get("files", {})
            for file_path, file_data in files.items():
                summary = file_data.get("summary", {})
                coverage_result["files"][file_path] = {
                    "statements": summary.get("num_statements", 0),
                    "covered": summary.get("covered_lines", 0),
                    "missing": summary.get("missing_lines", 0),
                    "percent": round(summary.get("percent_covered", 0), 2),
                }

        except Exception as e:
            print(f"Error parsing coverage JSON: {e}")

        return coverage_result

    # ============================================================================
    # FRONTEND TEST EXECUTION (JEST)
    # ============================================================================

    async def _run_frontend_tests(self, test_type: str = "all") -> Dict[str, Any]:
        """
        Run frontend tests using Jest (via npm test)

        Args:
            test_type: Type of tests to run

        Returns:
            Dictionary with test results
        """
        result = {
            "success": False,
            "framework": "jest",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration": 0,
            "failures": [],
            "coverage": {},
            "output": "",
            "error": None,
        }

        try:
            # Check if node_modules exists
            node_modules = os.path.join(self.frontend_path, "node_modules")
            if not os.path.exists(node_modules):
                result["error"] = 'node_modules not found. Run "npm install" first.'
                return result

            # Build Jest command
            cmd = ["npm", "test", "--", "--json", "--coverage", "--watchAll=false"]

            # Add test pattern if not all
            if test_type != "all":
                cmd.extend(["--testPathPattern", test_type])

            # Set environment variable to prevent interactive mode
            env = os.environ.copy()
            env["CI"] = "true"

            # Run tests
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.frontend_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await process.communicate()

            # Store output
            output = stdout.decode("utf-8")
            result["output"] = output

            if stderr:
                result["error"] = stderr.decode("utf-8")

            # Parse Jest JSON output
            json_results = self._parse_jest_output(output)
            result.update(json_results)

            # Parse coverage
            coverage_path = os.path.join(self.frontend_path, "coverage", "coverage-summary.json")
            if os.path.exists(coverage_path):
                coverage_results = self._parse_jest_coverage(coverage_path)
                result["coverage"] = coverage_results

            # Success if no failures
            result["success"] = result["failed"] == 0

        except FileNotFoundError:
            result["error"] = "npm not found. Make sure Node.js and npm are installed."
        except Exception as e:
            result["error"] = f"Error running frontend tests: {str(e)}"

        return result

    def _parse_jest_output(self, output: str) -> Dict[str, Any]:
        """Parse Jest JSON output"""
        result = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration": 0,
            "failures": [],
        }

        try:
            # Find JSON output in the text
            # Jest outputs JSON after "Test Results:"
            json_start = output.rfind("{")
            if json_start != -1:
                json_str = output[json_start:]
                test_data = json.loads(json_str)

                # Extract test statistics
                result["total"] = test_data.get("numTotalTests", 0)
                result["passed"] = test_data.get("numPassedTests", 0)
                result["failed"] = test_data.get("numFailedTests", 0)
                result["skipped"] = test_data.get("numPendingTests", 0)

                # Extract duration (in seconds)
                start_time = test_data.get("startTime", 0)
                end_time = (
                    test_data.get("testResults", [{}])[-1].get("endTime", 0) if test_data.get("testResults") else 0
                )
                if start_time and end_time:
                    result["duration"] = (end_time - start_time) / 1000

                # Extract failure details
                test_results = test_data.get("testResults", [])
                for test_file in test_results:
                    if test_file.get("status") == "failed":
                        for assertion in test_file.get("assertionResults", []):
                            if assertion.get("status") == "failed":
                                failure_messages = assertion.get("failureMessages", [])
                                result["failures"].append(
                                    {
                                        "test_name": assertion.get("title"),
                                        "file": test_file.get("name"),
                                        "message": (failure_messages[0] if failure_messages else "Test failed"),
                                        "details": "\n".join(failure_messages),
                                    }
                                )

        except json.JSONDecodeError:
            # Fallback to text parsing
            result.update(self._parse_jest_text_output(output))
        except Exception as e:
            print(f"Error parsing Jest output: {e}")

        return result

    def _parse_jest_text_output(self, output: str) -> Dict[str, Any]:
        """Fallback parser for Jest text output"""
        result = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}

        # Look for summary line like "Tests:       1 failed, 2 passed, 3 total"
        summary_match = re.search(
            r"Tests:\s+(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total",
            output,
        )
        if summary_match:
            result["failed"] = int(summary_match.group(1) or 0)
            result["passed"] = int(summary_match.group(2) or 0)
            result["total"] = int(summary_match.group(3) or 0)

        return result

    def _parse_jest_coverage(self, coverage_path: str) -> Dict[str, Any]:
        """Parse Jest coverage-summary.json"""
        coverage_result = {
            "statements": 0,
            "branches": 0,
            "functions": 0,
            "lines": 0,
            "files": {},
        }

        try:
            with open(coverage_path, "r") as f:
                coverage_data = json.load(f)

            # Get total coverage
            total = coverage_data.get("total", {})
            coverage_result["statements"] = round(total.get("statements", {}).get("pct", 0), 2)
            coverage_result["branches"] = round(total.get("branches", {}).get("pct", 0), 2)
            coverage_result["functions"] = round(total.get("functions", {}).get("pct", 0), 2)
            coverage_result["lines"] = round(total.get("lines", {}).get("pct", 0), 2)

            # Get file-level coverage
            for file_path, file_data in coverage_data.items():
                if file_path != "total":
                    coverage_result["files"][file_path] = {
                        "statements": round(file_data.get("statements", {}).get("pct", 0), 2),
                        "branches": round(file_data.get("branches", {}).get("pct", 0), 2),
                        "functions": round(file_data.get("functions", {}).get("pct", 0), 2),
                        "lines": round(file_data.get("lines", {}).get("pct", 0), 2),
                    }

        except Exception as e:
            print(f"Error parsing Jest coverage: {e}")

        return coverage_result

    # ============================================================================
    # REPORT GENERATION
    # ============================================================================

    def generate_report(self, format: str = "text") -> str:
        """
        Generate test report

        Args:
            format: Report format ('text', 'json', 'html')

        Returns:
            Formatted report string
        """
        if format == "json":
            return json.dumps(self.test_results, indent=2)
        elif format == "html":
            return self._generate_html_report()
        else:  # text
            return self._generate_text_report()

    def _generate_text_report(self) -> str:
        """Generate plain text report"""
        lines = []
        lines.append("=" * 80)
        lines.append("TEST RESULTS REPORT")
        lines.append("=" * 80)
        lines.append(f"Timestamp: {self.test_results.get('timestamp', 'N/A')}")
        lines.append(f"Overall Success: {'✅ PASS' if self.test_results.get('overall_success') else '❌ FAIL'}")
        lines.append("")

        # Summary
        lines.append("SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Total Tests:   {self.test_results.get('total_tests', 0)}")
        lines.append(f"Passed:        {self.test_results.get('passed_tests', 0)} ✅")
        lines.append(f"Failed:        {self.test_results.get('failed_tests', 0)} ❌")
        lines.append(f"Skipped:       {self.test_results.get('skipped_tests', 0)} ⏭️")
        lines.append(f"Success Rate:  {self.test_results.get('success_rate', 0):.2f}%")
        lines.append("")

        # Backend results
        if self.test_results.get("backend"):
            lines.append("BACKEND TESTS (pytest)")
            lines.append("-" * 80)
            backend = self.test_results["backend"]
            lines.append(f"Status:   {'✅ PASS' if backend.get('success') else '❌ FAIL'}")
            lines.append(f"Total:    {backend.get('total', 0)}")
            lines.append(f"Passed:   {backend.get('passed', 0)}")
            lines.append(f"Failed:   {backend.get('failed', 0)}")
            lines.append(f"Skipped:  {backend.get('skipped', 0)}")
            lines.append(f"Duration: {backend.get('duration', 0):.2f}s")

            # Coverage
            coverage = backend.get("coverage", {})
            if coverage:
                lines.append(f"Coverage: {coverage.get('coverage_percent', 0)}%")

            # Failures
            failures = backend.get("failures", [])
            if failures:
                lines.append("\nFailed Tests:")
                for failure in failures:
                    lines.append(f"  - {failure.get('test_name')} ({failure.get('class_name')})")
                    lines.append(f"    Message: {failure.get('message')}")

            lines.append("")

        # Frontend results
        if self.test_results.get("frontend"):
            lines.append("FRONTEND TESTS (Jest)")
            lines.append("-" * 80)
            frontend = self.test_results["frontend"]
            lines.append(f"Status:   {'✅ PASS' if frontend.get('success') else '❌ FAIL'}")
            lines.append(f"Total:    {frontend.get('total', 0)}")
            lines.append(f"Passed:   {frontend.get('passed', 0)}")
            lines.append(f"Failed:   {frontend.get('failed', 0)}")
            lines.append(f"Skipped:  {frontend.get('skipped', 0)}")
            lines.append(f"Duration: {frontend.get('duration', 0):.2f}s")

            # Coverage
            coverage = frontend.get("coverage", {})
            if coverage:
                lines.append(f"Coverage:")
                lines.append(f"  Statements: {coverage.get('statements', 0)}%")
                lines.append(f"  Branches:   {coverage.get('branches', 0)}%")
                lines.append(f"  Functions:  {coverage.get('functions', 0)}%")
                lines.append(f"  Lines:      {coverage.get('lines', 0)}%")

            # Failures
            failures = frontend.get("failures", [])
            if failures:
                lines.append("\nFailed Tests:")
                for failure in failures:
                    lines.append(f"  - {failure.get('test_name')}")
                    lines.append(f"    File: {failure.get('file')}")
                    lines.append(f"    Message: {failure.get('message')}")

            lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)

    def _generate_html_report(self) -> str:
        """Generate HTML report"""
        # Simplified HTML report
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Test Results Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
        .pass {{ color: green; }}
        .fail {{ color: red; }}
        .stats {{ margin: 10px 0; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
    </style>
</head>
<body>
    <h1>Test Results Report</h1>
    <div class="summary">
        <p><strong>Timestamp:</strong> {self.test_results.get('timestamp', 'N/A')}</p>
        <p class="{'pass' if self.test_results.get('overall_success') else 'fail'}">
            <strong>Overall Status:</strong> {'✅ PASS' if self.test_results.get('overall_success') else '❌ FAIL'}
        </p>
        <div class="stats">
            <p><strong>Total Tests:</strong> {self.test_results.get('total_tests', 0)}</p>
            <p><strong>Passed:</strong> {self.test_results.get('passed_tests', 0)}</p>
            <p><strong>Failed:</strong> {self.test_results.get('failed_tests', 0)}</p>
            <p><strong>Success Rate:</strong> {self.test_results.get('success_rate', 0):.2f}%</p>
        </div>
    </div>
</body>
</html>
        """
        return html

    async def save_to_database(self):
        """Save test results to database"""
        # This would integrate with the database to store test results
        # Implementation depends on your database schema
        pass


# Example usage (for testing)
if __name__ == "__main__":
    # This would be run after tests have been generated
    print("Test Runner Agent")
    print("Note: To test this, you need to generate test files first and have a project directory")
    print("Example: runner = TestRunner(project_id=1, project_path='/path/to/project')")
    print("         results = asyncio.run(runner.run_tests())")
