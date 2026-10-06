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
            # Return "" if not set so auth blocks treat missing creds as absent
            # (falsy) rather than attempting login with a literal "${VAR}" string.
            return os.getenv(var_name, "")

        return pattern.sub(replacer, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def extract_perf_flags(test_entry: dict) -> dict:
    """Extract per-test perf flags (critical, baseline_ms_override) from YAML entry.

    Defaults: critical=False, baseline_ms_override=None.
    Bad override values (non-int, ≤0) → None + log warning.
    """
    critical = bool(test_entry.get("critical", False))

    raw_override = test_entry.get("baseline_ms_override")
    override = None
    if raw_override is not None:
        if isinstance(raw_override, int) and not isinstance(raw_override, bool) and raw_override > 0:
            override = raw_override
        else:
            logger.warning(
                "Invalid baseline_ms_override=%r in test %r — falling back to auto-baseline",
                raw_override,
                test_entry.get("name"),
            )

    return {"critical": critical, "baseline_ms_override": override}


def execute_spec(spec, session=None, suite_id=None, run_id=None, skip_auth=False):
    """
    Execute all tests in a parsed spec.

    Args:
        spec: Parsed YAML spec dict with 'suite' and 'tests' keys.
        session: Optional requests.Session (created if not provided).
        suite_id: Parent suite id — required for visual_snapshot tests so
            baselines can be loaded from qa_visual_baselines, and for
            ux_score so scores can be keyed by suite.
        run_id: Parent run id — used by ux_score to write to
            qa_ux_rubric_scores keyed by run.
        skip_auth: If True, do not authenticate. Caller guarantees ``session``
            is already authenticated against the spec's base_url. Used by the
            scheduled batch runner to share one session across suites and avoid
            single-worker auth contention (Path B of PR #507 follow-up).

    Returns:
        List of result dicts.
    """
    # Resolve ${ENV_VAR} references (specs from DB still have placeholders)
    spec = _resolve_env_vars(spec)
    suite = spec.get("suite", {})
    tests = spec.get("tests", [])
    base_url = suite.get("base_url", os.environ.get("PLATFORM_URL", "http://archie_platform:3000")).rstrip("/")
    auth = suite.get("auth", {})

    if session is None:
        session = http_requests.Session()

    # `auth.mode: browser` — the site signs in through a REDIRECT (what-the-fact.com/login -> the platform's
    # OAuth / Account Center), not a form this HTTP session can POST to: WTF's /login answers a POST with 405,
    # so the HTTP pre-login below failed 3x and errored every test before the browser runner — which CAN follow
    # the redirect and has its own login (qa_e2e_runner.authenticate) — was ever reached (run 3994, 2026-10-06).
    # Opt-in per suite; nothing else sets it, so every existing suite behaves exactly as before. Only `e2e`
    # tests authenticate in the browser: any other test type in the same suite would run UNAUTHENTICATED.
    browser_auth = str(auth.get("mode", "")).strip().lower() == "browser"
    if browser_auth and any(t.get("type") != "e2e" for t in tests):
        logger.warning(
            "suite %s sets auth.mode=browser but has non-e2e tests; those run without a session",
            suite.get("name", "?"),
        )

    # Authenticate if credentials provided — retry up to 3 times with short
    # backoff. Previous policy (6×30s) ate 150s per flaky suite during bulk
    # scheduled runs and crowded out real diagnostics.
    if not skip_auth and not browser_auth and auth.get("username") and auth.get("password"):
        auth_error = None
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                _authenticate(session, base_url, auth)
                auth_error = None
                break
            except Exception as e:
                auth_error = e
                if attempt < max_attempts - 1:
                    logger.warning("Auth attempt %d/%d failed (%s) — retrying in 5s", attempt + 1, max_attempts, e)
                    time.sleep(5)
        if auth_error is not None:
            logger.error("Authentication failed after %d attempts: %s", max_attempts, auth_error)
            return [
                {
                    "test_name": t.get("name", f"test_{i}"),
                    "test_type": t.get("type", "unknown"),
                    "status": "error",
                    "error_message": f"Authentication failed after {max_attempts} attempts: {auth_error}",
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

    # Batch all visual_snapshot tests into one subprocess call (shared browser).
    # Each spec test explodes into N results (one per breakpoint), so we track
    # mapping by id(test) → list[result].
    visual_tests = [t for t in tests if t.get("type") == "visual_snapshot"]
    visual_results_map = {}
    if visual_tests:
        baselines = _fetch_visual_baselines(suite_id, visual_tests) if suite_id else []
        try:
            batch_results = _run_visual_snapshot_batch(visual_tests, base_url, auth, baselines)
            # Group results by the original test they came from (by name prefix).
            for t in visual_tests:
                name = t.get("name", "")
                visual_results_map[id(t)] = [r for r in batch_results if r.get("test_name", "").startswith(name)]
        except Exception as e:
            logger.error("Visual snapshot batch failed: %s", e)
            for t in visual_tests:
                visual_results_map[id(t)] = [
                    {
                        "test_name": t.get("name", "unknown"),
                        "test_type": "visual_snapshot",
                        "status": "error",
                        "error_message": f"Batch execution failed: {e}",
                    }
                ]

    # Batch all ux_score tests. Each explodes into N results (one per
    # breakpoint). Shared subprocess runs Playwright + vision dispatch.
    ux_tests = [t for t in tests if t.get("type") == "ux_score"]
    ux_results_map = {}
    if ux_tests:
        try:
            batch_results = _run_ux_score_batch(ux_tests, base_url, auth, suite_id, run_id)
            for t in ux_tests:
                name = t.get("name", "")
                ux_results_map[id(t)] = [r for r in batch_results if r.get("test_name", "").startswith(name)]
        except Exception as e:
            logger.error("UX score batch failed: %s", e)
            for t in ux_tests:
                ux_results_map[id(t)] = [
                    {
                        "test_name": t.get("name", "unknown"),
                        "test_type": "ux_score",
                        "status": "error",
                        "error_message": f"Batch execution failed: {e}",
                    }
                ]

    # Batch all tab_interaction tests into one subprocess call. Each explodes
    # into N results (page-load + one per tab), so we track by id(test) → list.
    tab_tests = [t for t in tests if t.get("type") == "tab_interaction"]
    tab_results_map = {}
    if tab_tests:
        try:
            batch_results = _run_tab_interaction_batch(tab_tests, base_url, auth)
            for t in tab_tests:
                name = t.get("name", "")
                tab_results_map[id(t)] = [r for r in batch_results if r.get("test_name", "").startswith(name)]
        except Exception as e:
            logger.error("Tab interaction batch failed: %s", e)
            for t in tab_tests:
                tab_results_map[id(t)] = [
                    {
                        "test_name": t.get("name", "unknown"),
                        "test_type": "tab_interaction",
                        "status": "error",
                        "error_message": f"Batch execution failed: {e}",
                    }
                ]

    results = []
    for test in tests:
        test_type = test.get("type", "api")
        try:
            if test_type == "api":
                result = _run_api_test(test, base_url, session, auth)
                result["perf_flags"] = extract_perf_flags(test)
                results.append(result)
            elif test_type == "page_load":
                result = _run_page_load_test(test, base_url, session)
                result["perf_flags"] = extract_perf_flags(test)
                results.append(result)
            elif test_type == "e2e":
                result = e2e_results_map.get(id(test)) or _run_e2e_test(test, base_url, auth)
                result["perf_flags"] = extract_perf_flags(test)
                results.append(result)
            elif test_type == "visual_snapshot":
                # May produce multiple results (one per breakpoint).
                sub_results = visual_results_map.get(id(test)) or [
                    {
                        "test_name": test.get("name", "unknown"),
                        "test_type": "visual_snapshot",
                        "status": "error",
                        "error_message": "Visual batch produced no results for this test.",
                    }
                ]
                results.extend(sub_results)
            elif test_type == "template_analysis":
                # Sync static scan — BeautifulSoup reads files directly from disk.
                from services.qa_template_analyzer import run_template_analysis_test

                sub_results = run_template_analysis_test(test)
                results.extend(sub_results)
            elif test_type == "ux_score":
                sub_results = ux_results_map.get(id(test)) or [
                    {
                        "test_name": test.get("name", "unknown"),
                        "test_type": "ux_score",
                        "status": "error",
                        "error_message": "UX batch produced no results for this test.",
                    }
                ]
                results.extend(sub_results)
            elif test_type == "tab_interaction":
                sub_results = tab_results_map.get(id(test)) or [
                    {
                        "test_name": test.get("name", "unknown"),
                        "test_type": "tab_interaction",
                        "status": "error",
                        "error_message": "Tab batch produced no results for this test.",
                    }
                ]
                results.extend(sub_results)
            else:
                results.append(
                    {
                        "test_name": test.get("name", "unknown"),
                        "test_type": test_type,
                        "status": "error",
                        "error_message": f"Unknown test type: {test_type}",
                    }
                )
        except Exception as e:
            results.append(
                {
                    "test_name": test.get("name", "unknown"),
                    "test_type": test_type,
                    "status": "error",
                    "error_message": str(e),
                }
            )

    return results


def _fetch_visual_baselines(suite_id, visual_tests):
    """Return list of baseline records matching the snapshot_names used by tests.

    Keeps the runner pure (no DB) — parent process fetches, subprocess receives
    the list via the base64 spec blob.
    """
    if not suite_id or not visual_tests:
        return []
    snapshot_names = list({t.get("snapshot_name") or t.get("name") for t in visual_tests})
    try:
        # Lazy import — database module isn't importable outside Flask/Docker.
        from database import get_db_cursor  # type: ignore
    except ImportError:
        try:
            from platform_v2.database import get_db_cursor  # type: ignore
        except ImportError:
            logger.warning("Could not import database module for baseline fetch.")
            return []

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """SELECT snapshot_name, breakpoint, baseline
                   FROM qa_visual_baselines
                   WHERE suite_id = %s AND snapshot_name = ANY(%s)""",
                (suite_id, snapshot_names),
            )
            rows = cur.fetchall() or []
            return [
                {
                    "snapshot_name": r["snapshot_name"],
                    "breakpoint": int(r["breakpoint"]),
                    "baseline": r["baseline"],
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("Failed to fetch visual baselines for suite %s: %s", suite_id, e)
        return []


def _run_visual_snapshot_batch(tests, base_url, auth, baselines):
    """Run all visual_snapshot tests in one Playwright subprocess.

    Mirrors the docker-exec-subprocess pattern used by _run_e2e_batch so that
    the Flask worker stays sync while Playwright runs async with its own loop.
    """
    import subprocess
    import json
    import base64

    spec = {
        "tests": tests,
        "base_url": base_url,
        "auth": auth,
        "baselines": baselines,
    }
    spec_b64 = base64.b64encode(json.dumps(spec).encode()).decode()

    # Budget: ~8s per test × breakpoints + a browser-start floor.
    total_bp = sum(len(t.get("breakpoints") or [1024]) for t in tests)
    timeout_s = max(90, total_bp * 12)

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
from services.qa_visual_runner import execute_batch

spec = json.loads(base64.b64decode('{spec_b64}'))
baselines = {{(b['snapshot_name'], int(b['breakpoint'])): b['baseline'] for b in spec.get('baselines', [])}}

results = asyncio.run(execute_batch(spec['tests'], spec['base_url'], spec.get('auth'), baselines))
print(json.dumps(results))
""",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )

    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout.strip().split("\n")[-1])
    err = (result.stderr or "Visual batch subprocess failed")[:500]
    # Return one error result per test (breakpoints lost in failure case).
    return [
        {
            "test_name": t.get("name", "unnamed_visual"),
            "test_type": "visual_snapshot",
            "url": f"{base_url}{t.get('path', '/')}",
            "status": "error",
            "error_message": err,
        }
        for t in tests
    ]


def _run_tab_interaction_batch(tests, base_url, auth):
    """Run all tab_interaction tests in one Playwright subprocess.

    Mirrors _run_visual_snapshot_batch so Flask stays sync while Playwright
    drives a single browser across every tab_interaction spec in the suite.
    """
    import subprocess
    import json
    import base64

    spec = {"tests": tests, "base_url": base_url, "auth": auth}
    spec_b64 = base64.b64encode(json.dumps(spec).encode()).decode()

    # Budget: ~5s per tab + 10s browser-start floor.
    total_tabs = sum(len(t.get("tabs") or []) for t in tests)
    timeout_s = max(60, total_tabs * 8 + 20)

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
from services.qa_tab_interaction_runner import execute_batch

spec = json.loads(base64.b64decode('{spec_b64}'))
results = asyncio.run(execute_batch(spec['tests'], spec['base_url'], spec.get('auth')))
print(json.dumps(results))
""",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )

    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout.strip().split("\n")[-1])
    err = (result.stderr or "Tab interaction batch subprocess failed")[:500]
    return [
        {
            "test_name": t.get("name", "unnamed_tab_interaction"),
            "test_type": "tab_interaction",
            "url": f"{base_url}{t.get('path', '/')}",
            "status": "error",
            "error_message": err,
        }
        for t in tests
    ]


def _run_ux_score_batch(tests, base_url, auth, suite_id, run_id):
    """Run all ux_score tests in one subprocess: Playwright + vision dispatch.

    Mirrors the _run_visual_snapshot_batch pattern — subprocess keeps the
    Flask worker sync while the scorer runs Playwright + vision calls
    asynchronously. The subprocess has DB access, so scores are written
    to qa_ux_rubric_scores directly from the scorer.
    """
    import subprocess
    import json
    import base64

    spec = {
        "tests": tests,
        "base_url": base_url,
        "auth": auth,
        "suite_id": suite_id,
        "run_id": run_id,
    }
    spec_b64 = base64.b64encode(json.dumps(spec).encode()).decode()

    # Budget: vision calls take 10-20s each on CPU-only vision model.
    total_calls = sum(len(t.get("breakpoints") or [1024]) for t in tests)
    timeout_s = max(180, total_calls * 60)

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
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain')
from services.qa_ux_scorer import execute_batch

spec = json.loads(base64.b64decode('{spec_b64}'))
results = asyncio.run(execute_batch(
    spec['tests'], spec['base_url'], spec.get('auth'),
    spec.get('suite_id'), spec.get('run_id'),
))
print(json.dumps(results))
""",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )

    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout.strip().split("\n")[-1])
    err = (result.stderr or "UX score batch subprocess failed")[:500]
    return [
        {
            "test_name": t.get("name", "unnamed_ux"),
            "test_type": "ux_score",
            "url": f"{base_url}{t.get('path', '/')}",
            "status": "error",
            "error_message": err,
        }
        for t in tests
    ]


def _authenticate(session, base_url, auth):
    """Authenticate the test session against the platform.

    Primary path: POST /api/qa/auth with the ARCHIE_QA_TOKEN — bypasses CSRF
    and rate limiting entirely. Works when the platform is running with the env
    var set (standard dev + CI config).

    Fallback: standard web-form login with CSRF double-submit cookie, for any
    environment where the QA token endpoint is not available.
    """
    qa_token = os.getenv("ARCHIE_QA_TOKEN", "")

    if qa_token:
        # Fast path: internal token auth, no CSRF, no rate limiting
        qa_url = f"{base_url}/api/qa/auth"
        resp = session.post(
            qa_url,
            json={"token": qa_token, "username": auth["username"]},
            allow_redirects=True,
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("success"):
            # Verify session is active
            verify = session.get(f"{base_url}/dashboard", allow_redirects=True, timeout=15)
            if "/login" not in (verify.url or ""):
                logger.info("QA token auth succeeded for %s", auth["username"])
                return
        logger.warning("QA token auth failed (status=%s), falling back to form login", resp.status_code)

    # Fallback: web-form login with CSRF double-submit cookie
    login_url = f"{base_url}/login"

    # Step 1: GET /login to seed the Flask session + archie_csrf cookie
    session.get(login_url, allow_redirects=True, timeout=15)
    csrf_token = session.cookies.get("archie_csrf", "")

    payload = {
        "username": auth["username"],
        "password": auth["password"],
        "_csrf_token": csrf_token,
    }
    resp = session.post(login_url, data=payload, allow_redirects=True, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"Login returned status {resp.status_code} for user {auth['username']}")

    # Follow redirects on the verification check — during gunicorn startup a
    # worker may temporarily 302 /dashboard before settling.  What matters is
    # where we land: /dashboard (auth OK) vs /login (auth failed / bad creds).
    verify = session.get(f"{base_url}/dashboard", allow_redirects=True, timeout=15)
    final_url = verify.url or ""
    if verify.status_code >= 400 or "/login" in final_url:
        raise RuntimeError(
            f"Auth verification failed for {auth['username']}: "
            f"landed on {final_url!r} (status {verify.status_code}) — "
            f"bad credentials or platform not ready"
        )
    logger.info(
        "Authenticated as %s (verified: dashboard status=%s url=%s)",
        auth["username"],
        verify.status_code,
        final_url,
    )


def _run_api_test(test, base_url, session, auth):
    """
    Execute an API test using requests.

    Checks: expect.status, expect.json_contains, expect.json_nonempty,
    expect.min_items, expect.json_gt, expect.path, expect.max_response_ms.
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

    # Per-test timeout override. LLM-backed endpoints (devotional, prayer,
    # workout generation, etc.) need >30s on cold-load — wake-on-demand for a
    # barracked agent + Ollama model load + generation can run 60-120s.
    # Default stays 30s so non-LLM tests fail fast.
    timeout_s = test.get("timeout_ms", 30000) / 1000.0

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
            timeout=timeout_s,
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

        # Check data-nonempty assertions (standalone coverage — KB #270283).
        # json_contains can't express "non-empty" and throws on top-level arrays,
        # so these are the checks that actually catch an empty-but-HTTP-200 site.
        #   expect.json_nonempty: true  -> JSON must be a non-empty list or dict
        #   expect.min_items: N         -> top-level JSON list/dict length >= N
        #   expect.json_gt: {key: N}    -> resp_json[key] > N (numeric, for stat dicts)
        if expect.get("json_nonempty") or expect.get("min_items") is not None or expect.get("json_gt"):
            try:
                rj = resp.json()
            except ValueError:
                result["assertions"]["json_parse"] = "fail"
                result["status"] = "fail"
                result["error_message"] = (result.get("error_message") or "") + " Response is not valid JSON."
                rj = None
            if rj is not None:
                # Optional dotted re-root so the assertions below can target
                # nested data, e.g. {"ok": true, "records": [...]} with
                # `path: records` + `min_items: 1`. A missing path is a failure.
                path = expect.get("path")
                if path:
                    node = rj
                    for part in str(path).split("."):
                        node = node.get(part) if isinstance(node, dict) else None
                        if node is None:
                            break
                    if node is None:
                        result["assertions"]["json_path"] = "fail"
                        result["status"] = "fail"
                        result["error_message"] = (
                            result.get("error_message") or ""
                        ) + f" json path {path!r} not found or null."
                    rj = node
                if rj is not None:
                    if expect.get("json_nonempty"):
                        nonempty_ok = bool(rj)
                        result["assertions"]["json_nonempty"] = "pass" if nonempty_ok else "fail"
                        if not nonempty_ok:
                            result["status"] = "fail"
                            result["error_message"] = (result.get("error_message") or "") + " Expected non-empty JSON."
                    min_items = expect.get("min_items")
                    if min_items is not None:
                        n = len(rj) if isinstance(rj, (list, dict)) else 0
                        items_ok = n >= min_items
                        result["assertions"]["min_items"] = "pass" if items_ok else "fail"
                        if not items_ok:
                            result["status"] = "fail"
                            result["error_message"] = (
                                result.get("error_message") or ""
                            ) + f" Expected >= {min_items} items, got {n}."
                    json_gt = expect.get("json_gt")
                    if json_gt and isinstance(json_gt, dict) and isinstance(rj, dict):
                        for gt_key, threshold in json_gt.items():
                            actual = rj.get(gt_key)
                            gt_ok = (
                                isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual > threshold
                            )
                            result["assertions"][f"json_gt_{gt_key}"] = "pass" if gt_ok else "fail"
                            if not gt_ok:
                                result["status"] = "fail"
                                result["error_message"] = (
                                    result.get("error_message") or ""
                                ) + f" Expected {gt_key} > {threshold}, got {actual!r}."

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

    # Per-test timeout override (mirrors _run_api_test).
    timeout_s = test.get("timeout_ms", 30000) / 1000.0

    try:
        start = time.time()
        resp = session.get(url, allow_redirects=True, timeout=timeout_s)
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

        # Check body_contains (substring search in full response body)
        body_contains = expect.get("body_contains")
        if body_contains:
            body_ok = body_contains in resp.text
            result["assertions"]["body_contains"] = "pass" if body_ok else "fail"
            if not body_ok:
                result["status"] = "fail"
                result["error_message"] = (
                    result.get("error_message") or ""
                ) + f" Body does not contain '{body_contains}'."

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
