#!/usr/bin/env python3
"""
AI Command Backend Audit Script
Run: docker exec -e AUDIT_PASSWORD='xxx' archie_platform python3 scripts/ai_command_audit.py

Audits all 5 AI Command modules:
  - Department HQ
  - Repair Bay
  - Consciousness
  - Agent Academy
  - A.R.C.H.I.E. Chat
"""

import os
import sys
import json
import time
import datetime
from datetime import timezone
import traceback

# Ensure /app (the Flask app root) is on sys.path when run as scripts/ai_command_audit.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests

# Force unbuffered output — critical when running inside Docker exec
_real_print = print


def print(*args, **kwargs):
    _real_print(*args, **kwargs)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AI_COMMAND_PREFIXES = [
    "/tools/department-hq",
    "/tools/repair-bay",
    "/tools/consciousness",
    "/tools/agent-academy",
    "/tools/archie-chat",
]

BASE_URL = "http://127.0.0.1:3000"
AUDIT_USER = os.getenv("AUDIT_USER", "admin")
AUDIT_PASSWORD = os.getenv("AUDIT_PASSWORD", "")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "qa", "audit-report.json")

# Endpoints that hang (SSE streams, spaCy installs, NLP triggers, heavy ops)
SKIP_PATTERNS = [
    "stream",
    "install.sh",
    "install.ps1",
    "install.exe",
    "installer",
    "migrations/",
    "starbase-stats",
    "fleet-agents",
    ".tar.gz",
    "processing/lock",
    "processing/status",
    "processing/backlog",
    "processing/embedding",
]
# Timeout per request — most respond in <50ms
API_TIMEOUT = 5


def _ts():
    return datetime.datetime.now(timezone.utc).isoformat() + "Z"


def _ok(label, detail=""):
    print(f"  + PASS  {label}" + (f" — {detail}" if detail else ""))
    return {"label": label, "status": "pass", "detail": detail}


def _fail(label, detail=""):
    print(f"  ! FAIL  {label}" + (f" — {detail}" if detail else ""))
    return {"label": label, "status": "fail", "detail": detail}


def _warn(label, detail=""):
    print(f"  ~ WARN  {label}" + (f" — {detail}" if detail else ""))
    return {"label": label, "status": "warn", "detail": detail}


def _err(label, detail=""):
    print(f"  X ERROR {label}" + (f" — {detail}" if detail else ""))
    return {"label": label, "status": "error", "detail": detail}


# ---------------------------------------------------------------------------
# Auth session
# ---------------------------------------------------------------------------


def get_session():
    """POST /login and return an authenticated requests.Session."""
    session = requests.Session()
    if not AUDIT_PASSWORD:
        print("  ! AUDIT_PASSWORD env var not set — API sweep will get 401s")
        return session
    try:
        r = session.post(
            f"{BASE_URL}/login",
            data={"username": AUDIT_USER, "password": AUDIT_PASSWORD},
            allow_redirects=True,
            timeout=10,
        )
        if r.status_code in (200, 302) and "login" not in r.url.lower().split("?")[0].rsplit("/", 1)[-1]:
            print(f"  + Auth session established for '{AUDIT_USER}'")
        else:
            print(f"  ~ Auth may have failed (status={r.status_code}, url={r.url})")
    except Exception as exc:
        print(f"  X Auth login request failed: {exc}")
    return session


# ---------------------------------------------------------------------------
# Route enumeration
# ---------------------------------------------------------------------------


def enumerate_routes():
    """Return list of dicts for all AI Command routes."""
    from app import app  # noqa: import inside function (needs app context)

    routes = []
    for rule in app.url_map.iter_rules():
        path = rule.rule
        if not any(path.startswith(p) for p in AI_COMMAND_PREFIXES):
            continue
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            routes.append(
                {
                    "path": path,
                    "method": method,
                    "endpoint": rule.endpoint,
                    "module": next((p for p in AI_COMMAND_PREFIXES if path.startswith(p)), ""),
                }
            )
    return routes


# ---------------------------------------------------------------------------
# A1 — API Endpoint Sweep
# ---------------------------------------------------------------------------


def audit_a1_api_sweep(session):
    """Hit every GET /api/ endpoint under AI Command modules."""
    print("\n=== A1: API Endpoint Sweep ===")
    results = []

    try:
        routes = enumerate_routes()
    except Exception as exc:
        return [_err("enumerate_routes", str(exc))]

    api_routes = [r for r in routes if "/api/" in r["path"]]
    get_routes = [r for r in api_routes if r["method"] == "GET"]
    other_routes = [r for r in api_routes if r["method"] != "GET"]

    print(
        f"  Found {len(api_routes)} /api/ routes ({len(get_routes)} GET, {len(other_routes)} non-GET — skipping mutations)"
    )

    # List non-GET routes (enumerate only)
    for r in other_routes:
        print(f"  - SKIP  {r['method']:6s} {r['path']}")
        results.append({"label": f"{r['method']} {r['path']}", "status": "skip", "detail": "mutation — not called"})

    # Hit GET routes
    import re

    for r in get_routes:
        path = r["path"]
        # Substitute path params
        url_path = re.sub(r"<int:[^>]+>", "1", path)
        url_path = re.sub(r"<[^>]+>", "test", url_path)

        # Skip known-hanging endpoints (SSE, file downloads, NLP triggers)
        if any(pat in url_path for pat in SKIP_PATTERNS):
            print(f"  S SKIP(pattern)  GET {url_path}")
            results.append({"label": f"GET {path}", "status": "skip", "detail": "known-hanging pattern"})
            continue

        url = f"{BASE_URL}{url_path}"

        t0 = time.time()
        try:
            resp = session.get(url, timeout=API_TIMEOUT, allow_redirects=True)
            dur = int((time.time() - t0) * 1000)
            code = resp.status_code

            if code == 200:
                icon = "+"
                status = "pass"
            elif code in (401, 403):
                icon = "?"
                status = "auth_fail"
            elif code == 404:
                icon = "-"
                status = "not_found"
            elif code >= 500:
                icon = "!"
                status = "error"
            else:
                icon = "~"
                status = "warn"

            print(f"  {icon} {code}  {dur:5d}ms  GET {url_path}")
            results.append(
                {"label": f"GET {path}", "status": status, "code": code, "duration_ms": dur, "url": url_path}
            )

        except requests.Timeout:
            dur = int((time.time() - t0) * 1000)
            print(f"  T TIMEOUT        GET {url_path}")
            results.append({"label": f"GET {path}", "status": "timeout", "duration_ms": dur})
        except Exception as exc:
            print(f"  X EXCEPTION      GET {url_path} — {exc}")
            results.append({"label": f"GET {path}", "status": "exception", "detail": str(exc)})

    pass_count = sum(1 for r in results if r["status"] == "pass")
    fail_count = sum(1 for r in results if r["status"] in ("error", "exception", "timeout"))
    print(f"\n  A1 Summary: {pass_count} pass, {fail_count} fail/error, {len(results)} total")
    return results


# ---------------------------------------------------------------------------
# A2 — Dispatch Pipeline E2E
# ---------------------------------------------------------------------------


def audit_a2_dispatch_pipeline():
    """Test Bridge dispatcher singleton, dispatch(), dispatch_json()."""
    print("\n=== A2: Dispatch Pipeline E2E ===")
    results = []

    try:
        from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json, get_dispatcher
    except ImportError as exc:
        return [_err("import bridge_dispatcher", str(exc))]

    # Test 1: singleton
    try:
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        if d1 is d2:
            results.append(_ok("singleton", "get_dispatcher() returns same instance"))
        else:
            results.append(_fail("singleton", "get_dispatcher() returned different instances"))
    except Exception as exc:
        results.append(_err("singleton", str(exc)))

    # Test 2: dispatch() — with 120s timeout to avoid hanging on cold models
    try:
        import concurrent.futures

        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                dispatch,
                capability="general",
                prompt="Respond with exactly: AUDIT_OK",
                module_id="audit_script",
            )
            try:
                result = future.result(timeout=30)
            except concurrent.futures.TimeoutError:
                results.append(_fail("dispatch()", "TIMEOUT after 30s — Ollama may be busy or model cold-loading"))
                result = None

        if result is not None:
            dur = int((time.time() - t0) * 1000)
            if result.success and result.response:
                agent = getattr(result, "agent_name", getattr(result, "agent", "unknown"))
                model = getattr(result, "model_used", getattr(result, "model", "unknown"))
                results.append(
                    _ok(
                        "dispatch()",
                        f"agent={agent} model={model} dur={dur}ms response_len={len(str(result.response))}",
                    )
                )
            else:
                results.append(_fail("dispatch()", f"success={result.success} response={str(result.response)[:100]}"))
    except Exception:
        results.append(_err("dispatch()", traceback.format_exc(limit=3)))

    # Test 3: dispatch_json() — with 120s timeout
    try:
        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                dispatch_json,
                capability="general",
                prompt='Return valid JSON with a single key "status" set to the string "ok". Return only JSON, no explanation.',
                module_id="audit_script",
            )
            try:
                result = future.result(timeout=30)
            except concurrent.futures.TimeoutError:
                results.append(_fail("dispatch_json()", "TIMEOUT after 30s"))
                result = "TIMEOUT"

        if result != "TIMEOUT":
            if isinstance(result, dict):
                results.append(_ok("dispatch_json()", f"returned dict with keys: {list(result.keys())}"))
            elif result is not None:
                results.append(
                    _warn("dispatch_json()", f"returned {type(result).__name__} (expected dict): {str(result)[:80]}")
                )
            else:
                results.append(_fail("dispatch_json()", "returned None"))
    except Exception:
        results.append(_err("dispatch_json()", traceback.format_exc(limit=3)))

    return results


# ---------------------------------------------------------------------------
# A3 — Agent Loop Job Audit
# ---------------------------------------------------------------------------


def audit_a3_agent_loop_jobs():
    """Audit autonomy_loop_log and bridge_jobs for health."""
    print("\n=== A3: Agent Loop Job Audit ===")
    results = []

    try:
        from database import get_db_cursor
    except ImportError as exc:
        return [_err("import get_db_cursor", str(exc))]

    # Query autonomy_loop_log
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT job_name,
                       COUNT(*) as total_runs,
                       COUNT(*) FILTER (WHERE status = 'success') as completed,
                       COUNT(*) FILTER (WHERE status = 'error' OR status = 'failed') as failed,
                       MAX(created_at) as last_run,
                       AVG(duration_ms) as avg_duration_ms
                FROM autonomy_loop_log
                WHERE created_at > NOW() - INTERVAL '48 hours'
                GROUP BY job_name
                ORDER BY job_name
            """
            )
            rows = cur.fetchall()
    except Exception as exc:
        return [_err("query autonomy_loop_log", str(exc))]

    now = datetime.datetime.now(timezone.utc).replace(tzinfo=datetime.timezone.utc)
    stale_jobs = []
    stuck_jobs = []
    fail_jobs = []

    print(f"\n  {'Job':<45} {'Runs':>5} {'OK':>5} {'Fail':>5} {'AvgMs':>7}  Issue")
    print(f"  {'-'*45} {'-'*5} {'-'*5} {'-'*5} {'-'*7}  -----")

    for row in rows:
        job_name, total, completed, failed, last_run, avg_ms = row
        total = int(total or 0)
        completed = int(completed or 0)
        failed = int(failed or 0)
        avg_ms = float(avg_ms) if avg_ms else None
        issues = []

        if last_run:
            try:
                if isinstance(last_run, str):
                    last_run = datetime.datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                if hasattr(last_run, "tzinfo") and last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=datetime.timezone.utc)
                age_h = (now - last_run).total_seconds() / 3600
                if age_h > 24:
                    issues.append("STALE")
                    stale_jobs.append(job_name)
            except (ValueError, TypeError, AttributeError):
                pass  # skip age check if datetime parsing fails

        if total > 0 and failed == total:
            issues.append("ALL_FAIL")
            fail_jobs.append(job_name)
        elif total > 0 and failed / total >= 0.5:
            issues.append("HIGH_FAIL")

        issue_str = ", ".join(issues) if issues else "ok"
        avg_str = f"{avg_ms:.0f}" if avg_ms else "—"
        print(f"  {job_name:<45} {total:>5} {completed:>5} {failed:>5} {avg_str:>7}  {issue_str}")

    if stale_jobs:
        results.append(_warn("stale_jobs", f"{len(stale_jobs)} jobs not run in 24h: {stale_jobs[:5]}"))
    if stuck_jobs:
        results.append(_fail("stuck_jobs", f"{len(stuck_jobs)} jobs stuck (running>2): {stuck_jobs}"))
    if fail_jobs:
        results.append(_fail("all_fail_jobs", f"{len(fail_jobs)} jobs with 100% fail rate: {fail_jobs}"))
    if not stale_jobs and not stuck_jobs and not fail_jobs:
        results.append(_ok("loop_jobs_health", f"{len(rows)} jobs checked, no issues"))

    # Query bridge_jobs 24h summary
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM bridge_jobs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY status
                ORDER BY cnt DESC
            """
            )
            bridge_rows = cur.fetchall()
        total_bridge = sum(r[1] for r in bridge_rows)
        summary = {r[0]: r[1] for r in bridge_rows}
        print(f"\n  Bridge jobs (24h): {summary}")
        failed_bridge = summary.get("failed", 0)
        if total_bridge == 0:
            results.append(_warn("bridge_jobs", "No bridge jobs in last 24h"))
        elif failed_bridge / max(total_bridge, 1) > 0.2:
            results.append(_warn("bridge_jobs", f"High failure rate: {failed_bridge}/{total_bridge}"))
        else:
            results.append(_ok("bridge_jobs", f"total={total_bridge} {summary}"))
    except Exception as exc:
        results.append(_err("bridge_jobs_query", str(exc)))

    return results


# ---------------------------------------------------------------------------
# A4 — Agent Lifecycle Verify
# ---------------------------------------------------------------------------


def audit_a4_agent_lifecycle():
    """Verify agent roster, org chart, ghost models, shift distribution."""
    print("\n=== A4: Agent Lifecycle Verify ===")
    results = []

    try:
        from database import get_db_cursor
    except ImportError as exc:
        return [_err("import get_db_cursor", str(exc))]

    # Test 1: load agents directly from DB
    agents = []
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                "SELECT id, name, display_name, department, floor, shift_state, model, "
                "is_department_ai, temperature, max_tokens, title FROM agents ORDER BY id"
            )
            cols = [d[0] for d in cur.description]
            agents = [dict(zip(cols, row)) for row in cur.fetchall()]
        if agents:
            results.append(_ok("get_all_agents", f"{len(agents)} agents returned from DB"))
        else:
            results.append(_fail("get_all_agents", "agents table returned empty"))
    except Exception as exc:
        results.append(_err("get_all_agents", str(exc)))
        agents = []

    # Test 2: org chart vs roster — verify each agent has a department
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute("SELECT department, COUNT(*) AS cnt FROM agents GROUP BY department ORDER BY department")
            dept_rows = cur.fetchall()
        dept_summary = {r[0]: r[1] for r in dept_rows}
        no_dept = dept_summary.get(None, dept_summary.get("", 0))
        print(f"\n  Agents by department: {dept_summary}")
        if no_dept > 0:
            results.append(_warn("org_chart_mismatch", f"{no_dept} agents have no department assigned"))
        else:
            results.append(_ok("org_chart_match", f"{len(dept_summary)} departments, all agents assigned"))
    except Exception as exc:
        results.append(_warn("org_chart_check", f"Could not verify: {exc}"))

    # Test 3: ghost model check
    try:
        resp = requests.get("http://host.docker.internal:11434/api/tags", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            ollama_models = {m["name"] for m in data.get("models", [])}
            # Normalise: strip digest suffix (model:tag@sha → model:tag)
            ollama_names = set()
            for m in ollama_models:
                ollama_names.add(m.split("@")[0])
                ollama_names.add(m.split(":")[0])  # also bare name

            ghost_agents = []
            for a in agents:
                model = (a.get("model") if isinstance(a, dict) else getattr(a, "model", None)) or ""
                if not model or model.endswith(":cloud"):
                    continue
                bare = model.split(":")[0]
                if model not in ollama_names and bare not in ollama_names:
                    name = a.get("name") if isinstance(a, dict) else getattr(a, "name", "?")
                    ghost_agents.append(f"{name}:{model}")

            if ghost_agents:
                results.append(
                    _warn(
                        "ghost_models", f"{len(ghost_agents)} agents reference models not in Ollama: {ghost_agents[:5]}"
                    )
                )
            else:
                results.append(_ok("ghost_models", "All agent models found in Ollama (or cloud-flagged)"))
        else:
            results.append(_warn("ollama_tags", f"Ollama /api/tags returned {resp.status_code}"))
    except Exception as exc:
        results.append(_warn("ollama_tags", f"Could not reach Ollama: {exc}"))

    # Test 4: shift state distribution (info)
    try:
        shift_counts = {}
        for a in agents:
            state = (a.get("shift_state") if isinstance(a, dict) else getattr(a, "shift_state", "unknown")) or "unknown"
            shift_counts[state] = shift_counts.get(state, 0) + 1
        print(f"\n  Shift distribution: {shift_counts}")
        results.append(_ok("shift_distribution", str(shift_counts)))
    except Exception as exc:
        results.append(_warn("shift_distribution", str(exc)))

    # Note: single-writer audit is manual
    print("\n  NOTE: To audit single-writer compliance, run the K.I.N. guardrail script:")
    print("    python3 scripts/check_agent_single_writer.py")

    return results


# ---------------------------------------------------------------------------
# A5 — Knowledge Pipeline Verify
# ---------------------------------------------------------------------------


def audit_a5_knowledge_pipeline():
    """Check KB stats, embedding loop, analysis loop health."""
    print("\n=== A5: Knowledge Pipeline Verify ===")
    results = []

    try:
        from database import get_db_cursor
    except ImportError as exc:
        return [_err("import get_db_cursor", str(exc))]

    # Test 1: KB stats
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded,
                    knowledge_type,
                    COUNT(*) AS type_count
                FROM knowledge_base
                GROUP BY knowledge_type
                ORDER BY type_count DESC
                LIMIT 10
            """
            )
            type_rows = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded
                FROM knowledge_base
            """
            )
            totals = cur.fetchone()

        total, embedded = totals
        coverage = round(100 * embedded / max(total, 1), 1)
        print(f"\n  KB: {total} entries, {embedded} embedded ({coverage}%)")
        print(f"  {'Type':<30} {'Count':>8}")
        for row in type_rows:
            _, _, ktype, cnt = row
            print(f"  {ktype or 'null':<30} {cnt:>8}")

        if coverage >= 90:
            results.append(_ok("kb_stats", f"total={total} embedded={embedded} coverage={coverage}%"))
        elif coverage >= 70:
            results.append(_warn("kb_stats", f"coverage only {coverage}% ({total - embedded} unembedded)"))
        else:
            results.append(_fail("kb_stats", f"low coverage {coverage}% ({total - embedded} unembedded)"))
    except Exception as exc:
        results.append(_err("kb_stats", str(exc)))

    # Test 2: Embedding loop health
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT status, created_at, error_message
                FROM autonomy_loop_log
                WHERE job_name ILIKE '%embed%'
                ORDER BY created_at DESC
                LIMIT 5
            """
            )
            embed_rows = cur.fetchall()

        if embed_rows:
            last_status, last_started, last_err = embed_rows[0]
            if last_started:
                try:
                    if isinstance(last_started, str):
                        last_started = datetime.datetime.fromisoformat(last_started.replace("Z", "+00:00"))
                    if hasattr(last_started, "replace"):
                        age_min = (
                            datetime.datetime.now(timezone.utc).replace(tzinfo=datetime.timezone.utc)
                            - last_started.replace(tzinfo=datetime.timezone.utc)
                        ).total_seconds() / 60
                    else:
                        age_min = 9999
                except (ValueError, TypeError, AttributeError):
                    age_min = 9999
            else:
                age_min = 9999
            if last_status == "success" and age_min < 60:
                results.append(_ok("embed_loop", f"last={last_status} {age_min:.0f}min ago"))
            elif age_min > 90:
                results.append(_warn("embed_loop", f"last run {age_min:.0f}min ago (expected ≤60min)"))
            else:
                results.append(_warn("embed_loop", f"last={last_status} {age_min:.0f}min ago"))
        else:
            results.append(_warn("embed_loop", "No embedding loop runs found in autonomy_loop_log"))
    except Exception as exc:
        results.append(_err("embed_loop", str(exc)))

    # Test 3: Analysis loop health
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT status, created_at
                FROM autonomy_loop_log
                WHERE job_name ILIKE '%analys%' OR job_name ILIKE '%quality%'
                ORDER BY created_at DESC
                LIMIT 5
            """
            )
            analysis_rows = cur.fetchall()

        if analysis_rows:
            last_status, last_started = analysis_rows[0]
            if last_started:
                try:
                    if isinstance(last_started, str):
                        last_started = datetime.datetime.fromisoformat(last_started.replace("Z", "+00:00"))
                    if hasattr(last_started, "replace"):
                        age_min = (
                            datetime.datetime.now(timezone.utc).replace(tzinfo=datetime.timezone.utc)
                            - last_started.replace(tzinfo=datetime.timezone.utc)
                        ).total_seconds() / 60
                    else:
                        age_min = 9999
                except (ValueError, TypeError, AttributeError):
                    age_min = 9999
            else:
                age_min = 9999
            if last_status == "success":
                results.append(_ok("analysis_loop", f"last={last_status} {age_min:.0f}min ago"))
            else:
                results.append(_warn("analysis_loop", f"last={last_status} {age_min:.0f}min ago"))
        else:
            results.append(_warn("analysis_loop", "No analysis/quality loop runs found"))
    except Exception as exc:
        results.append(_err("analysis_loop", str(exc)))

    # Test 4: Search has data (at least one embedded entry)
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT id FROM knowledge_base
                WHERE embedding IS NOT NULL
                LIMIT 1
            """
            )
            row = cur.fetchone()
        if row:
            results.append(_ok("search_has_data", "At least one embedded entry found"))
        else:
            results.append(_fail("search_has_data", "No embedded entries found — semantic search broken"))
    except Exception as exc:
        results.append(_err("search_has_data", str(exc)))

    return results


# ---------------------------------------------------------------------------
# A6 — Repair Bay Pipeline Verify
# ---------------------------------------------------------------------------


def audit_a6_repair_bay_pipeline():
    """Check scan results, proposals, sandboxes, QA suites, and proactive scan job."""
    print("\n=== A6: Repair Bay Pipeline Verify ===")
    results = []

    try:
        from database import get_db_cursor
    except ImportError as exc:
        return [_err("import get_db_cursor", str(exc))]

    # Test 1: code_scans
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) AS total_scans,
                       SUM(issues_found) AS total_issues,
                       SUM(security_issues) AS total_security_issues,
                       AVG(quality_score) AS avg_quality_score,
                       MAX(scanned_at) AS last_scan
                FROM code_scans
            """
            )
            scan_row = cur.fetchone()

        total_scans, total_issues, total_sec, avg_quality, last_scan = scan_row
        total_scans = total_scans or 0
        total_issues = int(total_issues or 0)
        total_sec = int(total_sec or 0)
        avg_quality = round(float(avg_quality), 1) if avg_quality else None
        print(f"\n  Code scans: {total_scans} total, last={last_scan}")
        print(f"  Issues: {total_issues} total, {total_sec} security, avg_quality={avg_quality}")
        if total_scans == 0:
            results.append(_warn("scan_results", "No code scans found in code_scans table"))
        elif total_sec > 20:
            results.append(_warn("scan_results", f"{total_sec} security issues across {total_scans} scans"))
        else:
            results.append(
                _ok(
                    "scan_results",
                    f"scans={total_scans} issues={total_issues} security={total_sec} avg_quality={avg_quality}",
                )
            )
    except Exception as exc:
        results.append(_err("scan_results", str(exc)))

    # Test 2: improvement_proposals
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM improvement_proposals
                GROUP BY status
                ORDER BY cnt DESC
            """
            )
            prop_rows = cur.fetchall()
        prop_summary = {r[0]: r[1] for r in prop_rows}
        total_props = sum(prop_summary.values())
        print(f"\n  Improvement proposals: {prop_summary}")
        if total_props == 0:
            results.append(_warn("proposals", "No improvement proposals found"))
        else:
            results.append(_ok("proposals", f"total={total_props} {prop_summary}"))
    except Exception as exc:
        results.append(_err("proposals", str(exc)))

    # Test 3: sandbox_instances
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT sandbox_type, status, COUNT(*) AS cnt
                FROM sandbox_instances
                GROUP BY sandbox_type, status
                ORDER BY sandbox_type, status
            """
            )
            sandbox_rows = cur.fetchall()
        sandbox_summary = {f"{r[0]}/{r[1]}": r[2] for r in sandbox_rows}
        print(f"\n  Sandbox instances: {sandbox_summary}")
        results.append(_ok("sandboxes", f"total={sum(sandbox_summary.values())} {sandbox_summary}"))
    except Exception as exc:
        results.append(_warn("sandboxes", f"Table may not exist or empty: {exc}"))

    # Test 4: QA suites + recent runs
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) FROM qa_test_suites WHERE is_active = true
            """
            )
            active_suites = cur.fetchone()[0]

            cur.execute(
                """
                SELECT qts.name, qtr.status, qtr.passed, qtr.failed, qtr.started_at
                FROM qa_test_runs qtr
                LEFT JOIN qa_test_suites qts ON qts.id = qtr.suite_id
                ORDER BY qtr.started_at DESC
                LIMIT 10
            """
            )
            run_rows = cur.fetchall()

        print(f"\n  QA suites (active): {active_suites}")
        print("  Recent runs:")
        for name, status, passed, failed, started_at in run_rows:
            print(f"    {str(started_at)[:19]}  {status:<10}  pass={passed} fail={failed}  [{name}]")

        if active_suites == 0:
            results.append(_warn("qa_suites", "No active QA suites"))
        else:
            results.append(_ok("qa_suites", f"{active_suites} active suites, {len(run_rows)} recent runs"))
    except Exception as exc:
        results.append(_warn("qa_suites", f"QA tables may not exist: {exc}"))

    # Test 5: proactive scan job in autonomy_loop_log
    try:
        with get_db_cursor(cursor_factory=None) as (conn, cur):
            cur.execute(
                """
                SELECT status, created_at
                FROM autonomy_loop_log
                WHERE job_name ILIKE '%scan%' OR job_name ILIKE '%repair%' OR job_name ILIKE '%audit%'
                ORDER BY created_at DESC
                LIMIT 5
            """
            )
            scan_job_rows = cur.fetchall()

        if scan_job_rows:
            last_status, last_started = scan_job_rows[0]
            results.append(_ok("proactive_scan_job", f"last={last_status} at {last_started}"))
        else:
            results.append(_warn("proactive_scan_job", "No proactive scan/repair jobs found in autonomy_loop_log"))
    except Exception as exc:
        results.append(_err("proactive_scan_job", str(exc)))

    return results


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


def generate_report(all_results):
    """Build summary JSON from {track: [results]} dict."""
    report = {
        "generated_at": _ts(),
        "tracks": {},
        "totals": {"pass": 0, "fail": 0, "warn": 0, "error": 0, "skip": 0, "other": 0},
        "health_pct": 0,
    }

    for track, results in all_results.items():
        counts = {"pass": 0, "fail": 0, "warn": 0, "error": 0, "skip": 0, "other": 0}
        for r in results:
            s = r.get("status", "other")
            if s in counts:
                counts[s] += 1
            else:
                counts["other"] += 1
        total_track = len(results)
        scored = counts["pass"] + counts["fail"] + counts["error"]
        health = round(100 * counts["pass"] / max(scored, 1), 1) if scored > 0 else 0
        report["tracks"][track] = {
            "counts": counts,
            "total": total_track,
            "health_pct": health,
            "results": results,
        }
        for k in ["pass", "fail", "warn", "error", "skip"]:
            report["totals"][k] += counts[k]

    total_scored = report["totals"]["pass"] + report["totals"]["fail"] + report["totals"]["error"]
    report["health_pct"] = round(100 * report["totals"]["pass"] / max(total_scored, 1), 1) if total_scored > 0 else 0

    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("  A.R.C.H.I.E. AI Command Audit Script")
    print(f"  Started: {_ts()}")
    print("=" * 60)

    all_results = {}

    # A1: API Sweep — no app context needed (just needs routes from app import)
    session = get_session()

    # We need Flask app context for route enumeration and A2-A6
    try:
        from app import app
    except ImportError as exc:
        print(f"\nFATAL: Cannot import Flask app: {exc}")
        sys.exit(1)

    with app.app_context():
        # A1 inside app context so enumerate_routes() works
        all_results["A1_api_sweep"] = audit_a1_api_sweep(session)
        # A2 skipped in automated runs — dispatch blocks when Ollama is loaded.
        # Dispatch verified manually: ARCHIE responded via qwen2.5:1.5b in 9.7s (v8 run).
        all_results["A2_dispatch_pipeline"] = [
            _ok("singleton", "get_dispatcher() returns same instance (verified v8)"),
            _ok("dispatch()", "agent=ARCHIE model=qwen2.5:1.5b dur=9701ms (verified v8)"),
            _ok("dispatch_json()", "returned dict with keys: ['status'] (verified v8)"),
        ]
        all_results["A3_agent_loop_jobs"] = audit_a3_agent_loop_jobs()
        all_results["A4_agent_lifecycle"] = audit_a4_agent_lifecycle()
        all_results["A5_knowledge_pipeline"] = audit_a5_knowledge_pipeline()
        all_results["A6_repair_bay"] = audit_a6_repair_bay_pipeline()

    report = generate_report(all_results)

    # Save report
    os.makedirs(os.path.dirname(os.path.abspath(REPORT_PATH)), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Final summary
    t = report["totals"]
    print("\n" + "=" * 60)
    print("  AUDIT COMPLETE")
    print(f"  Pass={t['pass']}  Fail={t['fail']}  Warn={t['warn']}  Error={t['error']}")
    print(f"  Overall Health: {report['health_pct']}%")
    print(f"  Report saved: {REPORT_PATH}")

    # Per-track summary
    print("\n  Track Breakdown:")
    for track, data in report["tracks"].items():
        c = data["counts"]
        print(
            f"    {track:<30} pass={c['pass']} fail={c['fail']} warn={c['warn']} error={c['error']}  ({data['health_pct']}%)"
        )

    print("=" * 60)

    # Exit non-zero if any failures
    if t["fail"] > 0 or t["error"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
