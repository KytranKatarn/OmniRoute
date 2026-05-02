"""P.R.O.B.E. QA Orchestrator Service — runs test suites, stores results, alerts on failure.

Import:
    from services.qa_service import run_suite, get_run_results, get_recent_runs,
        get_suites, create_suite_from_yaml
"""

import logging
import os
import re
import subprocess
import time

import requests as http_requests
from psycopg2.extras import Json

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Directory containing pytest module test files
PYTEST_MODULES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "qa",
    "tests",
    "modules",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_suite(suite_id, triggered_by="manual"):
    """Execute all specs in a test suite and record results.

    Returns dict: {success, run_id, status, total, passed, failed, errors}
    """
    # Fetch the suite
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, name, description, target_url, spec, suite_type "
            "FROM qa_test_suites WHERE id = %s AND is_active = true",
            (suite_id,),
        )
        suite = cur.fetchone()
        if not suite:
            return {"success": False, "error": f"Suite {suite_id} not found or inactive"}
        suite = dict(suite)

    # Create the run record
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO qa_test_runs (suite_id, triggered_by, status) " "VALUES (%s, %s, 'running') RETURNING id",
            (suite_id, triggered_by),
        )
        run_id = cur.fetchone()["id"]

    # Import spec runner inside function to avoid circular imports
    from services.qa_spec_runner import execute_spec

    # execute_spec takes the full spec dict {suite: ..., tests: [...]}
    # and returns a list of result dicts, one per test
    spec_data = suite.get("spec", {})

    passed = 0
    failed = 0
    errors = 0
    start_time = time.time()

    try:
        results = execute_spec(spec_data, suite_id=suite_id, run_id=run_id)
    except Exception as exc:
        logger.error("Suite %s execution failed: %s", suite_id, exc)
        results = [
            {
                "test_name": "suite_execution",
                "test_type": "api",
                "status": "error",
                "error_message": str(exc)[:500],
            }
        ]

    # NOTE: Pytest E2E tests run from the HOST (not inside Docker) because
    # Playwright needs Chromium which OOM-kills the container. The /archie-qa
    # slash command handles pytest execution and stores results separately.
    # _run_pytest_module() is available for host-side callers.

    # Store each result in DB
    for result in results:
        status = result.get("status", "error")
        if status == "pass":
            passed += 1
        elif status == "fail":
            failed += 1
        elif status == "skip":
            pass  # skips don't count as errors
        else:
            errors += 1

        # expected_status may be a list (e.g. [302, 401]) — store first value
        expected = result.get("expected_status")
        if isinstance(expected, list):
            expected = expected[0] if expected else None

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO qa_test_results
                   (run_id, test_name, test_type, status, url, method,
                    expected_status, actual_status, response_time_ms,
                    error_message, screenshot_path, assertions)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    run_id,
                    result.get("test_name", "unnamed"),
                    result.get("test_type", "unknown"),
                    status,
                    result.get("url"),
                    result.get("method"),
                    expected,
                    result.get("actual_status"),
                    result.get("response_time_ms"),
                    result.get("error_message"),
                    result.get("screenshot_path"),
                    Json(result.get("assertions")) if result.get("assertions") else None,
                ),
            )

    total = passed + failed + errors
    duration_ms = int((time.time() - start_time) * 1000)
    run_status = "completed" if failed == 0 and errors == 0 else "failed"

    # Update the run record with totals
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE qa_test_runs
               SET status = %s, total_tests = %s, passed = %s, failed = %s,
                   errors = %s, duration_ms = %s, completed_at = NOW()
               WHERE id = %s""",
            (run_status, total, passed, failed, errors, duration_ms, run_id),
        )

    # Alert on failures
    if failed > 0 or errors > 0:
        try:
            _send_qa_telegram_alert(
                suite_name=suite["name"],
                run_id=run_id,
                total=total,
                passed=passed,
                failed=failed,
                errors=errors,
                results=results,
            )
        except Exception as exc:
            logger.error("Telegram alert failed: %s", exc)

        # Auto-create Repair Bay proposals for actionable failures
        try:
            _create_proposals_from_failures(
                suite_name=suite["name"],
                suite_id=suite_id,
                run_id=run_id,
                results=results,
            )
        except Exception as exc:
            logger.error("Auto-proposal creation failed: %s", exc)

    return {
        "success": True,
        "run_id": run_id,
        "status": run_status,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
    }


def _run_pytest_module(suite_name):
    """Run pytest for a module if a matching test file exists.

    Looks for qa/tests/modules/{slug}.py where slug is the suite name
    with spaces and hyphens normalized to underscores.

    Returns list of result dicts, or empty list if no test file found.
    """
    # Try multiple slug strategies to match suite name to test file:
    # "AI Command — Consciousness" -> try: consciousness, ai_command_consciousness, department_hq
    candidates = []
    # 1. Last segment after em-dash or hyphen-dash
    if "—" in suite_name:
        last_part = suite_name.split("—")[-1].strip()
        candidates.append(re.sub(r"[\s\-\.]+", "_", last_part.lower().strip()))
    if " - " in suite_name:
        last_part = suite_name.split(" - ")[-1].strip()
        candidates.append(re.sub(r"[\s\-\.]+", "_", last_part.lower().strip()))
    # 2. Full name slugified
    candidates.append(re.sub(r"[\s\-—\.]+", "_", suite_name.lower().strip()))
    # 3. Just alphanumeric + underscores
    candidates.append(re.sub(r"[^a-z0-9]+", "_", suite_name.lower().strip()).strip("_"))

    test_file = None
    for slug in candidates:
        candidate_path = os.path.join(PYTEST_MODULES_DIR, f"{slug}.py")
        if os.path.exists(candidate_path):
            test_file = candidate_path
            break

    if not test_file:
        logger.debug("No pytest module for suite '%s' (tried %s)", suite_name, candidates)
        return []

    logger.info("Running pytest module: %s", test_file)
    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", test_file, "-v", "--tb=short", "--no-header", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return [
            {
                "test_name": f"pytest:{slug}:timeout",
                "test_type": "e2e",
                "status": "error",
                "error_message": "Pytest execution timed out after 120s",
            }
        ]
    except Exception as exc:
        return [
            {
                "test_name": f"pytest:{slug}:execution",
                "test_type": "e2e",
                "status": "error",
                "error_message": str(exc)[:500],
            }
        ]

    # Parse pytest -v output lines like:
    #   tests/modules/consciousness.py::test_consciousness_loads PASSED
    #   tests/modules/consciousness.py::test_consciousness_tabs FAILED
    results = []
    for line in output.splitlines():
        match = re.match(r".*::(\S+)\s+(PASSED|FAILED|ERROR|SKIPPED)", line)
        if match:
            test_name = match.group(1)
            raw_status = match.group(2)
            status_map = {"PASSED": "pass", "FAILED": "fail", "ERROR": "error", "SKIPPED": "skip"}
            results.append(
                {
                    "test_name": f"pytest:{test_name}",
                    "test_type": "e2e",
                    "status": status_map.get(raw_status, "error"),
                    "error_message": None,
                }
            )

    # If we got failures, try to extract error messages from the short traceback
    if proc.returncode != 0 and results:
        failure_blocks = re.split(r"_{3,}\s+", output)
        for block in failure_blocks:
            for r in results:
                if r["status"] == "fail" and r["test_name"].split(":")[-1] in block:
                    # Grab last line of the block as the assertion error
                    lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
                    if lines:
                        r["error_message"] = lines[-1][:500]

    if not results:
        logger.warning("Pytest ran but no test results parsed from output")
        logger.debug("Pytest output: %s", output[:2000])

    return results


def get_run_results(run_id):
    """Fetch a run and all its test results.

    Returns dict with run info + results list, or None if not found.
    """
    with get_db_cursor() as (conn, cur):
        # Fetch run
        cur.execute(
            """SELECT r.id, r.suite_id, r.triggered_by, r.status,
                      r.total_tests, r.passed, r.failed, r.errors,
                      r.duration_ms, r.report_path, r.started_at, r.completed_at,
                      s.name AS suite_name
               FROM qa_test_runs r
               JOIN qa_test_suites s ON s.id = r.suite_id
               WHERE r.id = %s""",
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        run = dict(row)

        # Fetch results
        cur.execute(
            """SELECT id, test_name, test_type, status, url, method,
                      expected_status, actual_status, response_time_ms,
                      error_message, screenshot_path, assertions, created_at
               FROM qa_test_results
               WHERE run_id = %s
               ORDER BY id""",
            (run_id,),
        )
        results = []
        for r in cur.fetchall():
            rd = dict(r)
            # Add viewable screenshot URL
            if rd.get("screenshot_path"):
                filename = rd["screenshot_path"].rsplit("/", 1)[-1]
                rd["screenshot_url"] = f"/api/qa/screenshots/{filename}"
            results.append(rd)

    run["results"] = results
    return run


def get_recent_runs(limit=20):
    """Fetch recent test runs with suite name, ordered by started_at DESC."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT r.id, r.suite_id, s.name AS suite_name,
                      r.triggered_by, r.status, r.total_tests,
                      r.passed, r.failed, r.errors,
                      r.duration_ms, r.started_at, r.completed_at
               FROM qa_test_runs r
               JOIN qa_test_suites s ON s.id = r.suite_id
               ORDER BY r.started_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_suites():
    """Fetch all active test suites."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, name, description, target_url, suite_type,
                      user_id, is_active, created_at, updated_at
               FROM qa_test_suites
               WHERE is_active = true
               ORDER BY name"""
        )
        return [dict(row) for row in cur.fetchall()]


def create_suite_from_yaml(file_path, suite_type="internal", user_id=None):
    """Load a YAML spec file and insert it as a new test suite.

    Returns the new suite_id.
    """
    from services.qa_spec_runner import load_spec_from_file

    spec_data = load_spec_from_file(file_path)

    name = spec_data.get("name", os.path.basename(file_path))
    description = spec_data.get("description", "")
    target_url = spec_data.get("target_url", "http://192.168.1.200:3000")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO qa_test_suites
               (name, description, target_url, spec, suite_type, user_id)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (name, description, target_url, Json(spec_data), suite_type, user_id),
        )
        suite_id = cur.fetchone()["id"]

    logger.info("Created QA suite '%s' (id=%s) from %s", name, suite_id, file_path)
    return suite_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _send_qa_telegram_alert(suite_name, run_id, total, passed, failed, errors, results):
    """Send a Telegram alert when a QA run has failures.

    Routes through telegram_service.send_agent() so all outbound messages go via
    the A.R.C.H.I.E. unified voice (director_report_service inbox).
    """
    FAIL_STATUSES = {"fail", "failed", "error"}

    # Build failure list (max 5)
    failure_lines = []
    for r in results:
        if r.get("status") in FAIL_STATUSES:
            name = r.get("test_name", "unknown")
            err = r.get("error_message", "no details")
            if len(err) > 120:
                err = err[:117] + "..."
            failure_lines.append(f"  - {name}: {err}")
            if len(failure_lines) >= 5:
                remaining = (failed + errors) - 5
                if remaining > 0:
                    failure_lines.append(f"  _...and {remaining} more_")
                break

    body = (
        f"Suite: *{suite_name}* | Run ID: `{run_id}`\n"
        f"Passed: {passed} | Failed: {failed} | Errors: {errors} | Total: {total}\n\n"
        "Failed tests:\n" + "\n".join(failure_lines)
    )

    # Visual regression section — call out CSS/style diffs explicitly
    visual_fails = [r for r in results if r.get("test_type") == "visual_snapshot" and r.get("status") in FAIL_STATUSES]
    if visual_fails:
        body += "\n\n🔴 *Visual Regressions:*\n"
        for r in visual_fails[:4]:
            name = r.get("test_name", "?")
            diffs = (r.get("assertions") or {}).get("diffs") or []
            if diffs:
                summary = "; ".join(f"{d['selector']}[{d['property']}]" for d in diffs[:3])
                if len(diffs) > 3:
                    summary += f" (+{len(diffs) - 3} more)"
            else:
                summary = r.get("error_message", "unknown diff")[:100]
            body += f"  `{name}`: {summary}\n"

    try:
        from services.telegram_service import send_agent

        send_agent(
            "P.R.O.B.E. QA Alert",
            body,
            source_agent="P.R.O.B.E.",
            source_department="Engineering & Technology",
        )
    except Exception as exc:
        logger.warning("Failed to send QA alert via telegram_service: %s", exc)


def _was_previously_passing(suite_id, test_name, current_run_id):
    """Check if a test passed in the most recent completed run before current_run_id.

    Returns True (regression), False (known failure), or None (no prior data).
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT tr.status
                   FROM qa_test_results tr
                   JOIN qa_test_runs r ON tr.run_id = r.id
                   WHERE r.suite_id = %s
                     AND tr.test_name = %s
                     AND r.id < %s
                     AND r.status IN ('completed', 'failed')
                   ORDER BY r.id DESC
                   LIMIT 1""",
                (suite_id, test_name, current_run_id),
            )
            row = cur.fetchone()
        if row:
            return row["status"] == "pass"
        return None  # first time this test has run
    except Exception as exc:
        logger.warning("Regression check failed for '%s': %s", test_name, exc)
        return None


def _create_proposals_from_failures(suite_name, run_id, results, suite_id=None):
    """Auto-create Repair Bay improvement proposals from QA test failures.

    Follows the scan_pipeline pattern: dedup by source + test_name,
    map severity from error type, insert into improvement_proposals.

    Regression detection: only creates proposals for tests that were passing
    in the most recent prior run — skips tests that have been consistently
    failing (the open dedup proposal already exists for those).
    """
    failures = [r for r in results if r.get("status") in ("fail", "error")]
    if not failures:
        return

    created = 0
    for result in failures:
        test_name = result.get("test_name", "unnamed")
        error_msg = result.get("error_message", "No details")
        test_type = result.get("test_type", "unknown")
        url = result.get("url", "")
        actual_status = result.get("actual_status")
        expected_status = result.get("expected_status")

        # Regression detection — skip consistently-failing tests (dedup handles them)
        was_passing = _was_previously_passing(suite_id, test_name, run_id) if suite_id else None
        is_regression = was_passing is True  # True = was passing → now failing = regression
        if was_passing is False:
            # Known failure — open proposal already exists (dedup below will confirm)
            logger.debug("Skipping proposal for '%s' — test was already failing", test_name)
            continue

        # Determine severity from error pattern
        if "SSL" in error_msg or "certificate" in error_msg.lower():
            severity = "high"
            category = "security"
        elif "Connection error" in error_msg or "timeout" in error_msg.lower():
            severity = "high"
            category = "availability"
        elif actual_status == 404:
            severity = "medium"
            category = "quality"
        elif actual_status and actual_status >= 500:
            severity = "high"
            category = "availability"
        else:
            severity = "medium"
            category = "quality"

        priority_map = {"high": "high", "medium": "medium", "low": "low"}
        risk_map = {"high": "medium", "medium": "low", "low": "low"}

        # Dedup: skip if open proposal exists for same source + test
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id FROM improvement_proposals
                   WHERE status NOT IN ('deployed', 'implemented', 'rejected',
                                        'archived', 'failed')
                     AND metadata->>'source' = 'qa_pipeline'
                     AND metadata->>'test_name' = %s""",
                (test_name,),
            )
            if cur.fetchone():
                logger.debug("Skipping proposal for '%s' — open proposal exists", test_name)
                continue

        # Build proposal content
        title = f"QA Failure: {test_name}"
        if len(title) > 120:
            title = title[:117] + "..."

        description = (
            f"**P.R.O.B.E. QA test failure detected**\n\n"
            f"- **Suite:** {suite_name}\n"
            f"- **Run ID:** {run_id}\n"
            f"- **Test:** {test_name} ({test_type})\n"
            f"- **URL:** {url}\n"
        )
        if expected_status and actual_status:
            description += f"- **Expected:** {expected_status} → **Got:** {actual_status}\n"
        description += f"- **Error:** {error_msg}\n"

        metadata = {
            "source": "qa_pipeline",
            "test_name": test_name,
            "test_type": test_type,
            "suite_name": suite_name,
            "suite_id": suite_id,
            "run_id": run_id,
            "url": url,
            "severity": severity,
            "is_regression": is_regression,
            "auto_generated": True,
        }

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO improvement_proposals
                   (title, category, description, priority, risk_level,
                    status, metadata, collaboration_enabled)
                   VALUES (%s, %s, %s, %s, %s, 'pending', %s, false)
                   RETURNING id""",
                (
                    title,
                    category,
                    description,
                    priority_map.get(severity, "medium"),
                    risk_map.get(severity, "low"),
                    Json(metadata),
                ),
            )
            proposal_id = cur.fetchone()["id"]
            created += 1
            logger.info(
                "Created proposal #%s for QA failure '%s' (%s)",
                proposal_id,
                test_name,
                severity,
            )

    if created:
        logger.info(
            "P.R.O.B.E. auto-created %d Repair Bay proposals from run #%s",
            created,
            run_id,
        )
