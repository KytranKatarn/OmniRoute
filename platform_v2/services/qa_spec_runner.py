"""
P.R.O.B.E. QA Test Spec Runner
===============================
Parses YAML test specs and executes tests using requests for API
and page_load tests. E2E tests deferred to Phase 2 (Playwright).

Usage:
    from services.qa_spec_runner import load_spec_from_file, execute_spec
    spec = load_spec_from_file("/path/to/spec.yaml")
    results = execute_spec(spec)
"""

import os
import re
import time
import logging
import yaml
import requests as http_requests
from dotenv import load_dotenv

# Load .env so QA specs can reference ${ARCHIE_TEST_PASSWORD} etc.
for env_path in ["/app/.env", "/mnt/archie_brain/platform_v2/.env"]:
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
        break

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = "/tmp/qa_reports/screenshots/"


def load_spec_from_file(file_path):
    """Load a YAML test spec file and resolve ${ENV_VAR} references."""
    with open(file_path, "r") as f:
        spec = yaml.safe_load(f)
    return _resolve_env_vars(spec)


def _resolve_env_vars(obj):
    """Recursively resolve ${VAR_NAME} patterns in all string values."""
    if isinstance(obj, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replacer(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))

        return pattern.sub(replacer, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def execute_spec(spec, session=None):
    """
    Execute all tests in a parsed spec.

    Args:
        spec: Parsed YAML spec dict with 'suite' and 'tests' keys.
        session: Optional requests.Session (created if not provided).

    Returns:
        List of result dicts.
    """
    # Resolve ${ENV_VAR} references (specs from DB still have placeholders)
    spec = _resolve_env_vars(spec)
    suite = spec.get("suite", {})
    tests = spec.get("tests", [])
    base_url = suite.get("base_url", "http://localhost:3000").rstrip("/")
    auth = suite.get("auth", {})

    if session is None:
        session = http_requests.Session()

    # Authenticate if credentials provided
    if auth.get("username") and auth.get("password"):
        try:
            _authenticate(session, base_url, auth)
        except Exception as e:
            logger.error("Authentication failed: %s", e)
            # Return error result for all tests if auth fails
            return [
                {
                    "test_name": t.get("name", f"test_{i}"),
                    "test_type": t.get("type", "unknown"),
                    "status": "error",
                    "error_message": f"Authentication failed: {e}",
                }
                for i, t in enumerate(tests)
            ]

    # Batch all e2e tests into one subprocess call for browser reuse
    e2e_tests = [t for t in tests if t.get("type") == "e2e"]
    e2e_results_map = {}
    if e2e_tests:
        try:
            batch_results = _run_e2e_batch(e2e_tests, base_url, auth)
            for i, r in enumerate(batch_results):
                e2e_results_map[id(e2e_tests[i])] = r
        except Exception as e:
            logger.error("E2E batch failed: %s", e)
            for t in e2e_tests:
                e2e_results_map[id(t)] = {
                    "test_name": t.get("name", "unknown"),
                    "test_type": "e2e",
                    "status": "error",
                    "error_message": f"Batch execution failed: {e}",
                }

    results = []
    for test in tests:
        test_type = test.get("type", "api")
        try:
            if test_type == "api":
                result = _run_api_test(test, base_url, session, auth)
            elif test_type == "page_load":
                result = _run_page_load_test(test, base_url, session)
            elif test_type == "e2e":
                result = e2e_results_map.get(id(test)) or _run_e2e_test(test, base_url, auth)
            else:
                result = {
                    "test_name": test.get("name", "unknown"),
                    "test_type": test_type,
                    "status": "error",
                    "error_message": f"Unknown test type: {test_type}",
                }
        except Exception as e:
            result = {
                "test_name": test.get("name", "unknown"),
                "test_type": test_type,
                "status": "error",
                "error_message": str(e),
            }
        results.append(result)

    return results


def _authenticate(session, base_url, auth):
    """POST to /login with username/password form data."""
    login_url = f"{base_url}/login"
    payload = {
        "username": auth["username"],
        "password": auth["password"],
    }
    resp = session.post(login_url, data=payload, allow_redirects=True, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Login returned status {resp.status_code} for user {auth['username']}")
    logger.info("Authenticated as %s (status %s)", auth["username"], resp.status_code)


def _run_api_test(test, base_url, session, auth):
    """
    Execute an API test using requests.

    Checks: expect.status, expect.json_contains, expect.max_response_ms.
    Uses allow_redirects=False so we can verify 302s.
    """
    test_name = test.get("name", "unnamed_api_test")
    method = test.get("method", "GET").upper()
    path = test.get("path", "/")
    url = f"{base_url}{path}"
    expect = test.get("expect", {})
    headers = test.get("headers", {})
    body = test.get("body", None)
    params = test.get("params", None)

    # If skip_auth is set, use a fresh unauthenticated session
    if test.get("skip_auth", False):
        req_session = http_requests.Session()
    else:
        req_session = session

    result = {
        "test_name": test_name,
        "test_type": "api",
        "url": url,
        "method": method,
        "status": "pass",
        "error_message": None,
        "assertions": {},
    }

    try:
        start = time.time()
        resp = req_session.request(
            method,
            url,
            headers=headers,
            json=body if body and method in ("POST", "PUT", "PATCH") else None,
            data=body if body and method not in ("POST", "PUT", "PATCH") else None,
            params=params,
            allow_redirects=False,
            timeout=30,
        )
        elapsed_ms = (time.time() - start) * 1000

        result["actual_status"] = resp.status_code
        result["response_time_ms"] = round(elapsed_ms, 2)

        # Check expected status
        expected_status = expect.get("status")
        if expected_status is not None:
            if isinstance(expected_status, list):
                status_ok = resp.status_code in expected_status
            else:
                status_ok = resp.status_code == expected_status
            result["expected_status"] = expected_status
            result["assertions"]["status_code"] = "pass" if status_ok else "fail"
            if not status_ok:
                result["status"] = "fail"
                result["error_message"] = f"Expected status {expected_status}, got {resp.status_code}"

        # Check json_contains
        json_contains = expect.get("json_contains")
        if json_contains and isinstance(json_contains, dict):
            try:
                resp_json = resp.json()
                for key, expected_val in json_contains.items():
                    actual_val = resp_json.get(key)
                    match = actual_val == expected_val
                    result["assertions"][f"json_{key}"] = "pass" if match else "fail"
                    if not match:
                        result["status"] = "fail"
                        result["error_message"] = (
                            result.get("error_message") or ""
                        ) + f" json_contains: {key} expected {expected_val!r}, got {actual_val!r}."
            except ValueError:
                result["assertions"]["json_parse"] = "fail"
                result["status"] = "fail"
                result["error_message"] = (result.get("error_message") or "") + " Response is not valid JSON."

        # Check max_response_ms
        max_ms = expect.get("max_response_ms")
        if max_ms is not None:
            time_ok = elapsed_ms <= max_ms
            result["assertions"]["response_time"] = "pass" if time_ok else "fail"
            if not time_ok:
                result["status"] = "fail"
                result["error_message"] = (
                    result.get("error_message") or ""
                ) + f" Response took {elapsed_ms:.0f}ms, max allowed {max_ms}ms."

    except http_requests.exceptions.Timeout:
        result["status"] = "error"
        result["error_message"] = "Request timed out"
    except http_requests.exceptions.ConnectionError as e:
        result["status"] = "error"
        result["error_message"] = f"Connection error: {e}"
    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)

    # Clean up error_message whitespace
    if result.get("error_message"):
        result["error_message"] = result["error_message"].strip()

    return result


def _run_page_load_test(test, base_url, session):
    """
    Basic page load test using requests (no Playwright).

    Checks: expect.status, expect.title_contains, expect.max_load_ms.
    """
    test_name = test.get("name", "unnamed_page_load_test")
    path = test.get("path", "/")
    url = f"{base_url}{path}"
    expect = test.get("expect", {})

    result = {
        "test_name": test_name,
        "test_type": "page_load",
        "url": url,
        "method": "GET",
        "status": "pass",
        "error_message": None,
        "assertions": {},
    }

    try:
        start = time.time()
        resp = session.get(url, allow_redirects=True, timeout=30)
        elapsed_ms = (time.time() - start) * 1000

        result["actual_status"] = resp.status_code
        result["response_time_ms"] = round(elapsed_ms, 2)

        # Check expected status
        expected_status = expect.get("status")
        if expected_status is not None:
            if isinstance(expected_status, list):
                status_ok = resp.status_code in expected_status
            else:
                status_ok = resp.status_code == expected_status
            result["expected_status"] = expected_status
            result["assertions"]["status_code"] = "pass" if status_ok else "fail"
            if not status_ok:
                result["status"] = "fail"
                result["error_message"] = f"Expected status {expected_status}, got {resp.status_code}"

        # Check title_contains (regex search in HTML <title>)
        title_contains = expect.get("title_contains")
        if title_contains:
            title_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
            page_title = title_match.group(1).strip() if title_match else ""
            title_ok = bool(re.search(title_contains, page_title, re.IGNORECASE))
            result["assertions"]["title_contains"] = "pass" if title_ok else "fail"
            if not title_ok:
                result["status"] = "fail"
                result["error_message"] = (
                    result.get("error_message") or ""
                ) + f" Title '{page_title}' does not match pattern '{title_contains}'."

        # Check max_load_ms
        max_ms = expect.get("max_load_ms")
        if max_ms is not None:
            time_ok = elapsed_ms <= max_ms
            result["assertions"]["load_time"] = "pass" if time_ok else "fail"
            if not time_ok:
                result["status"] = "fail"
                result["error_message"] = (
                    result.get("error_message") or ""
                ) + f" Page load took {elapsed_ms:.0f}ms, max allowed {max_ms}ms."

    except http_requests.exceptions.Timeout:
        result["status"] = "error"
        result["error_message"] = "Page load timed out"
    except http_requests.exceptions.ConnectionError as e:
        result["status"] = "error"
        result["error_message"] = f"Connection error: {e}"
    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)

    # Clean up error_message whitespace
    if result.get("error_message"):
        result["error_message"] = result["error_message"].strip()

    return result


def _run_e2e_batch(tests, base_url, auth, run_id=None):
    """Run multiple E2E tests in ONE docker exec, reusing the browser session.

    Saves ~3-4s per test on browser startup and avoids tmpfs exhaustion
    from launching 15+ Chromium processes in sequence.
    """
    import subprocess
    import json
    import base64

    spec = {"tests": tests, "base_url": base_url, "auth": auth, "run_id": run_id}
    spec_b64 = base64.b64encode(json.dumps(spec).encode()).decode()

    timeout_s = max(60, len(tests) * 15)  # ~15s per test budget

    result = subprocess.run(
        [
            "docker",
            "exec",
            "archie_platform",
            "python3",
            "-c",
            f"""
import asyncio, json, sys, base64
sys.path.insert(0, '/app')
from services.qa_e2e_runner import E2ERunner

spec = json.loads(base64.b64decode('{spec_b64}'))

async def run():
    runner = E2ERunner()
    return await runner.execute_batch(spec['tests'], spec['base_url'], spec.get('auth'), spec.get('run_id'))

results = asyncio.run(run())
print(json.dumps(results))
""",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )

    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout.strip().split("\n")[-1])
    else:
        err = (result.stderr or "Batch subprocess failed")[:500]
        return [
            {
                "test_name": t.get("name", "unnamed_e2e"),
                "test_type": "e2e",
                "url": f"{base_url}{t.get('path', '/')}",
                "status": "error",
                "error_message": err,
            }
            for t in tests
        ]


def _run_e2e_test(test, base_url, auth, run_id=None):
    """Run E2E test via Playwright inside Docker container."""
    import subprocess
    import json

    try:
        # Pass spec as base64-encoded JSON via env var to docker exec
        import base64

        spec = {"test": test, "base_url": base_url, "auth": auth, "run_id": run_id}
        spec_b64 = base64.b64encode(json.dumps(spec).encode()).decode()

        result = subprocess.run(
            [
                "docker",
                "exec",
                "archie_platform",
                "python3",
                "-c",
                f"""
import asyncio, json, sys, base64
sys.path.insert(0, '/app')
from services.qa_e2e_runner import E2ERunner

spec = json.loads(base64.b64decode('{spec_b64}'))

async def run():
    runner = E2ERunner()
    try:
        return await runner.execute(spec['test'], spec['base_url'], spec.get('auth'), spec.get('run_id'))
    finally:
        await runner.close()

result = asyncio.run(run())
print(json.dumps(result))
""",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip().split("\n")[-1])
        else:
            return {
                "test_name": test.get("name", "unnamed_e2e_test"),
                "test_type": "e2e",
                "url": f"{base_url}{test.get('path', '/')}",
                "status": "error",
                "error_message": (result.stderr or "Subprocess failed")[:500],
            }
    except ImportError:
        return {
            "test_name": test.get("name", "unnamed_e2e_test"),
            "test_type": "e2e",
            "url": f"{base_url}{test.get('path', '/')}",
            "status": "skip",
            "error_message": "Playwright not installed — run: playwright install chromium",
        }
    except Exception as e:
        return {
            "test_name": test.get("name", "unnamed_e2e_test"),
            "test_type": "e2e",
            "url": f"{base_url}{test.get('path', '/')}",
            "status": "error",
            "error_message": str(e),
        }
