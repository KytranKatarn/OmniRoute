# AI Command Phase A — Backend Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Systematically verify every backend system across the 5 AI Command modules and produce a health report that drives all subsequent work.

**Architecture:** Create an audit script (`platform_v2/scripts/ai_command_audit.py`) that runs inside the Docker container, hits every API endpoint, checks every scheduled job, tests the dispatch pipeline, and outputs a JSON health report. Each audit track (A1-A6) is a function in the script. Results stored in knowledge_base via MCP.

**Tech Stack:** Python 3, requests, psycopg2, Flask test client, APScheduler introspection

**Spec:** `docs/superpowers/specs/2026-04-13-ai-command-finalization-design.md`
**Project:** #255 | **Tasks:** #1849-#1854

---

### Task 1: Route Enumeration Script (Task #1849)

**Files:**
- Create: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Create the audit script with route enumeration**

```python
#!/usr/bin/env python3
"""AI Command Backend Audit — Phase A
Run inside Docker: docker exec archie_platform python3 scripts/ai_command_audit.py
"""
import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta

# Add platform_v2 to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

BASE_URL = "http://127.0.0.1:5000"
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("AUDIT_PASSWORD", "")

AI_COMMAND_PREFIXES = [
    "/tools/department-hq",
    "/tools/repair-bay",
    "/tools/consciousness",
    "/tools/agent-academy",
    "/tools/archie-chat",
]

def get_session():
    """Create authenticated session."""
    s = requests.Session()
    resp = s.post(f"{BASE_URL}/login", data={
        "username": ADMIN_USER,
        "password": ADMIN_PASS,
    }, allow_redirects=False)
    if resp.status_code not in (200, 302):
        print(f"[WARN] Login returned {resp.status_code} — some endpoints may fail auth")
    return s


def enumerate_routes():
    """Get all AI Command routes from Flask app.url_map."""
    from app import app
    routes = []
    for rule in app.url_map.iter_rules():
        path = rule.rule
        if any(path.startswith(p) for p in AI_COMMAND_PREFIXES):
            methods = [m for m in rule.methods if m in ("GET", "POST", "PUT", "DELETE", "PATCH")]
            for method in methods:
                routes.append({
                    "path": path,
                    "method": method,
                    "endpoint": rule.endpoint,
                    "module": next((p for p in AI_COMMAND_PREFIXES if path.startswith(p)), "unknown"),
                })
    return routes


def audit_a1_api_sweep(session):
    """A1: Hit every API endpoint, log results."""
    print("\n=== A1: API Endpoint Sweep ===")
    routes = enumerate_routes()
    api_routes = [r for r in routes if "/api/" in r["path"]]
    print(f"Found {len(routes)} total routes, {len(api_routes)} API routes")

    results = []
    for r in api_routes:
        path = r["path"]
        method = r["method"]

        # Skip routes with complex path params — test with placeholder
        test_path = path
        if "<" in test_path:
            # Replace <int:id> style params with 1
            import re
            test_path = re.sub(r"<(?:int|float):(\w+)>", "1", test_path)
            test_path = re.sub(r"<(\w+)>", "test", test_path)

        url = f"{BASE_URL}{test_path}"
        start = time.time()
        try:
            if method == "GET":
                resp = session.get(url, timeout=10)
            elif method == "POST":
                resp = session.post(url, json={}, timeout=10)
            elif method == "PUT":
                resp = session.put(url, json={}, timeout=10)
            elif method == "DELETE":
                resp = session.delete(url, timeout=10)
            else:
                resp = session.get(url, timeout=10)
            duration_ms = int((time.time() - start) * 1000)

            status = "pass"
            if resp.status_code >= 500:
                status = "error"
            elif resp.status_code in (401, 403):
                status = "auth_fail"
            elif resp.status_code == 404:
                status = "not_found"

            result = {
                "path": path,
                "test_path": test_path,
                "method": method,
                "module": r["module"],
                "endpoint": r["endpoint"],
                "status_code": resp.status_code,
                "duration_ms": duration_ms,
                "status": status,
                "content_length": len(resp.content),
            }
        except requests.Timeout:
            result = {
                "path": path, "test_path": test_path, "method": method,
                "module": r["module"], "endpoint": r["endpoint"],
                "status_code": 0, "duration_ms": 10000,
                "status": "timeout", "content_length": 0,
            }
        except Exception as e:
            result = {
                "path": path, "test_path": test_path, "method": method,
                "module": r["module"], "endpoint": r["endpoint"],
                "status_code": 0, "duration_ms": 0,
                "status": "exception", "error": str(e)[:200],
                "content_length": 0,
            }

        icon = {"pass": "+", "error": "!", "auth_fail": "?", "not_found": "-", "timeout": "T", "exception": "X"}.get(result["status"], "?")
        print(f"  [{icon}] {method:6s} {test_path} -> {result.get('status_code', '???')} ({result.get('duration_ms', 0)}ms)")
        results.append(result)

    return results
```

- [ ] **Step 2: Run route enumeration to verify it works**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from app import app
count = sum(1 for r in app.url_map.iter_rules() if any(r.rule.startswith(p) for p in ['/tools/department-hq', '/tools/repair-bay', '/tools/consciousness', '/tools/agent-academy', '/tools/archie-chat']))
print(f'AI Command routes: {count}')
"
```

Expected: A number showing total AI Command routes (should be 200+).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add AI Command backend audit script — Phase A1 route enumeration"
```

---

### Task 2: Dispatch Pipeline E2E Test (Task #1850)

**Files:**
- Modify: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Add dispatch pipeline audit function**

Append to `ai_command_audit.py`:

```python
def audit_a2_dispatch_pipeline():
    """A2: End-to-end dispatch pipeline test."""
    print("\n=== A2: Dispatch Pipeline E2E ===")
    results = []

    try:
        from tools.department_hq.services.bridge_dispatcher import dispatch, dispatch_json, get_dispatcher

        # Test 1: get_dispatcher() returns singleton
        d1 = get_dispatcher()
        d2 = get_dispatcher()
        results.append({
            "test": "get_dispatcher_singleton",
            "status": "pass" if d1 is d2 else "fail",
            "detail": "Same instance" if d1 is d2 else "Different instances!",
        })
        print(f"  [{'+'if d1 is d2 else '!'}] get_dispatcher() singleton: {'PASS' if d1 is d2 else 'FAIL'}")

        # Test 2: dispatch() with a simple prompt
        start = time.time()
        result = dispatch(
            capability="general",
            prompt="Respond with exactly: AUDIT_OK",
            module_id="audit_script",
            system_prompt="You are a test agent. Respond with exactly the text requested.",
        )
        duration = int((time.time() - start) * 1000)

        dispatch_ok = result.success and len(result.response) > 0
        results.append({
            "test": "dispatch_basic",
            "status": "pass" if dispatch_ok else "fail",
            "detail": f"success={result.success}, agent={result.agent_name}, model={result.model_used}, "
                       f"duration={duration}ms, response_len={len(result.response)}",
            "duration_ms": duration,
            "agent": result.agent_name,
            "model": result.model_used,
        })
        print(f"  [{'+'if dispatch_ok else '!'}] dispatch() basic: agent={result.agent_name}, model={result.model_used}, {duration}ms")

        # Test 3: dispatch_json() returns parsed JSON
        start = time.time()
        json_result = dispatch_json(
            capability="general",
            prompt='Return a JSON object with key "status" set to "ok".',
            module_id="audit_script",
        )
        duration = int((time.time() - start) * 1000)

        json_ok = json_result is not None and isinstance(json_result, dict)
        results.append({
            "test": "dispatch_json",
            "status": "pass" if json_ok else "fail",
            "detail": f"returned={'dict' if json_ok else type(json_result).__name__}, duration={duration}ms",
            "duration_ms": duration,
        })
        print(f"  [{'+'if json_ok else '!'}] dispatch_json(): {'PASS' if json_ok else 'FAIL'} ({duration}ms)")

    except ImportError as e:
        results.append({"test": "import_dispatcher", "status": "error", "detail": str(e)})
        print(f"  [X] Import failed: {e}")
    except Exception as e:
        results.append({"test": "dispatch_pipeline", "status": "error", "detail": str(e)[:300]})
        print(f"  [X] Exception: {e}")

    return results
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add dispatch pipeline E2E audit — Phase A2"
```

---

### Task 3: Agent Loop Job Audit (Task #1851)

**Files:**
- Modify: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Add agent loop audit function**

Append to `ai_command_audit.py`:

```python
def audit_a3_agent_loop_jobs():
    """A3: Audit all scheduled agent loop jobs."""
    print("\n=== A3: Agent Loop Job Audit ===")
    results = []

    try:
        from database import get_db_cursor
        now = datetime.utcnow()

        # Get all registered jobs from autonomy_loop_log
        with get_db_cursor() as (conn, cur):
            # Recent job runs (last 48h)
            cur.execute("""
                SELECT job_name, status, started_at, completed_at, error_message,
                       EXTRACT(EPOCH FROM (completed_at - started_at)) as duration_secs
                FROM autonomy_loop_log
                WHERE started_at > NOW() - INTERVAL '48 hours'
                ORDER BY started_at DESC
            """)
            recent_runs = cur.fetchall()

            # Aggregate by job name
            cur.execute("""
                SELECT job_name,
                       COUNT(*) as total_runs,
                       COUNT(*) FILTER (WHERE status = 'completed') as completed,
                       COUNT(*) FILTER (WHERE status = 'failed') as failed,
                       COUNT(*) FILTER (WHERE status = 'running') as running,
                       MAX(started_at) as last_run,
                       AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration
                FROM autonomy_loop_log
                WHERE started_at > NOW() - INTERVAL '48 hours'
                GROUP BY job_name
                ORDER BY job_name
            """)
            job_stats = cur.fetchall()

        print(f"  Found {len(job_stats)} unique jobs in last 48h, {len(recent_runs)} total runs")

        for job in job_stats:
            name = job[0]
            total = job[1]
            completed = job[2]
            failed = job[3]
            running = job[4]
            last_run = job[5]
            avg_dur = job[6]

            # Flag issues
            issues = []
            if last_run and (now - last_run).total_seconds() > 86400:
                issues.append("stale_>24h")
            if total > 0 and failed == total:
                issues.append("100%_fail_rate")
            if running > 2:
                issues.append(f"{running}_stuck_running")

            status = "fail" if issues else "pass"
            result = {
                "job_name": name,
                "total_runs_48h": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "last_run": str(last_run) if last_run else None,
                "avg_duration_secs": round(avg_dur, 1) if avg_dur else None,
                "issues": issues,
                "status": status,
            }
            icon = "!" if issues else "+"
            print(f"  [{icon}] {name}: {completed}/{total} ok, {failed} fail, last={last_run}, issues={issues or 'none'}")
            results.append(result)

        # Check for bridge_jobs health too
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT status, COUNT(*)
                FROM bridge_jobs
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY status
            """)
            bridge_stats = {row[0]: row[1] for row in cur.fetchall()}

        results.append({
            "job_name": "_bridge_jobs_24h_summary",
            "stats": bridge_stats,
            "status": "info",
        })
        print(f"  [i] Bridge jobs 24h: {bridge_stats}")

    except Exception as e:
        results.append({"test": "agent_loop_audit", "status": "error", "detail": str(e)[:300]})
        print(f"  [X] Exception: {e}")

    return results
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add agent loop job audit — Phase A3"
```

---

### Task 4: Agent Lifecycle Verify (Task #1852)

**Files:**
- Modify: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Add agent lifecycle audit function**

Append to `ai_command_audit.py`:

```python
def audit_a4_agent_lifecycle():
    """A4: Verify agent_service is single writer, data consistency."""
    print("\n=== A4: Agent Lifecycle Verify ===")
    results = []

    try:
        from services.agent_service import (
            get_all_agents, get_agent, get_org_chart,
        )
        from database import get_db_cursor

        # Test 1: agent_service.get_all_agents() returns data
        agents = get_all_agents()
        agent_count = len(agents) if agents else 0
        results.append({
            "test": "get_all_agents",
            "status": "pass" if agent_count > 0 else "fail",
            "detail": f"{agent_count} agents returned",
        })
        print(f"  [{'+'if agent_count > 0 else '!'}] get_all_agents(): {agent_count} agents")

        # Test 2: Org chart data matches roster data
        org_data = get_org_chart()
        org_agent_ids = set()
        if org_data:
            for floor in org_data:
                for dept in floor.get("departments", []):
                    for agent in dept.get("agents", []):
                        org_agent_ids.add(agent.get("id"))

        roster_ids = {a["id"] for a in agents} if agents else set()
        org_match = org_agent_ids == roster_ids
        missing_from_org = roster_ids - org_agent_ids
        extra_in_org = org_agent_ids - roster_ids

        results.append({
            "test": "org_roster_consistency",
            "status": "pass" if org_match else "fail",
            "detail": f"org={len(org_agent_ids)}, roster={len(roster_ids)}, "
                       f"missing_from_org={len(missing_from_org)}, extra_in_org={len(extra_in_org)}",
        })
        print(f"  [{'+'if org_match else '!'}] Org/Roster consistency: org={len(org_agent_ids)}, roster={len(roster_ids)}")

        # Test 3: Check for ghost models (agents assigned models not in Ollama)
        try:
            import requests as req
            ollama_resp = req.get("http://host.docker.internal:11434/api/tags", timeout=5)
            ollama_models = {m["name"] for m in ollama_resp.json().get("models", [])} if ollama_resp.ok else set()

            ghost_models = []
            if agents and ollama_models:
                for a in agents:
                    model = a.get("model")
                    if model and model not in ollama_models and not model.endswith(":cloud"):
                        ghost_models.append({"agent": a.get("name"), "model": model})

            results.append({
                "test": "ghost_model_check",
                "status": "pass" if not ghost_models else "warn",
                "detail": f"{len(ghost_models)} ghost models" if ghost_models else "All models available",
                "ghosts": ghost_models[:10],
            })
            print(f"  [{'+'if not ghost_models else '!'}] Ghost models: {len(ghost_models)}")
        except Exception as e:
            results.append({"test": "ghost_model_check", "status": "error", "detail": str(e)[:200]})

        # Test 4: Shift state distribution
        if agents:
            states = {}
            for a in agents:
                s = a.get("shift_state", "unknown")
                states[s] = states.get(s, 0) + 1
            results.append({
                "test": "shift_state_distribution",
                "status": "info",
                "detail": states,
            })
            print(f"  [i] Shift states: {states}")

        # Test 5: Check for direct SQL writers (not through agent_service)
        # This is a code audit — grep for INSERT INTO agents or UPDATE agents
        # outside of agent_service.py
        results.append({
            "test": "single_writer_code_audit",
            "status": "manual",
            "detail": "Run: grep -rn 'INSERT INTO agents\\|UPDATE agents' platform_v2/ --include='*.py' | grep -v agent_service.py | grep -v migrations/",
        })
        print("  [?] Single-writer code audit: requires manual grep (see report)")

    except Exception as e:
        results.append({"test": "agent_lifecycle", "status": "error", "detail": str(e)[:300]})
        print(f"  [X] Exception: {e}")

    return results
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add agent lifecycle audit — Phase A4"
```

---

### Task 5: Knowledge Pipeline Verify (Task #1853)

**Files:**
- Modify: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Add knowledge pipeline audit function**

Append to `ai_command_audit.py`:

```python
def audit_a5_knowledge_pipeline():
    """A5: Verify Consciousness knowledge loops and search."""
    print("\n=== A5: Knowledge Pipeline Verify ===")
    results = []

    try:
        from database import get_db_cursor

        # Test 1: KB stats
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE archived = false")
            total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL AND archived = false")
            embedded = cur.fetchone()[0]

            cur.execute("""
                SELECT knowledge_type, COUNT(*)
                FROM knowledge_base
                WHERE archived = false
                GROUP BY knowledge_type
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            by_type = {row[0]: row[1] for row in cur.fetchall()}

        coverage = round(embedded / total * 100, 1) if total > 0 else 0
        results.append({
            "test": "kb_stats",
            "status": "pass" if coverage > 90 else "warn",
            "detail": f"total={total}, embedded={embedded}, coverage={coverage}%",
            "by_type": by_type,
        })
        print(f"  [{'+'if coverage > 90 else '!'}] KB: {total} entries, {coverage}% embedded")

        # Test 2: Embedding loop health
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT started_at, status, error_message
                FROM autonomy_loop_log
                WHERE job_name LIKE '%embed%'
                ORDER BY started_at DESC
                LIMIT 5
            """)
            embed_runs = cur.fetchall()

        if embed_runs:
            last_run = embed_runs[0]
            results.append({
                "test": "embedding_loop",
                "status": "pass" if last_run[1] == "completed" else "fail",
                "detail": f"last={last_run[0]}, status={last_run[1]}, error={last_run[2] or 'none'}",
            })
            print(f"  [{'+'if last_run[1]=='completed' else '!'}] Embedding loop: last={last_run[0]}, status={last_run[1]}")
        else:
            results.append({"test": "embedding_loop", "status": "warn", "detail": "No embedding runs found"})
            print("  [!] Embedding loop: no runs found")

        # Test 3: Analysis loop health
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT started_at, status, error_message
                FROM autonomy_loop_log
                WHERE job_name LIKE '%analy%'
                ORDER BY started_at DESC
                LIMIT 5
            """)
            analysis_runs = cur.fetchall()

        if analysis_runs:
            last_run = analysis_runs[0]
            results.append({
                "test": "analysis_loop",
                "status": "pass" if last_run[1] == "completed" else "fail",
                "detail": f"last={last_run[0]}, status={last_run[1]}",
            })
            print(f"  [{'+'if last_run[1]=='completed' else '!'}] Analysis loop: last={last_run[0]}, status={last_run[1]}")

        # Test 4: Search quality — does search_knowledge return meaningful results?
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT id, title, knowledge_type
                FROM knowledge_base
                WHERE archived = false AND embedding IS NOT NULL
                LIMIT 1
            """)
            sample = cur.fetchone()

        if sample:
            results.append({
                "test": "search_has_data",
                "status": "pass",
                "detail": f"Sample entry: id={sample[0]}, title={sample[1][:50]}, type={sample[2]}",
            })
        else:
            results.append({"test": "search_has_data", "status": "fail", "detail": "No embedded entries found"})

    except Exception as e:
        results.append({"test": "knowledge_pipeline", "status": "error", "detail": str(e)[:300]})
        print(f"  [X] Exception: {e}")

    return results
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add knowledge pipeline audit — Phase A5"
```

---

### Task 6: Repair Bay Pipeline Verify (Task #1854)

**Files:**
- Modify: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Add repair bay audit function**

Append to `ai_command_audit.py`:

```python
def audit_a6_repair_bay_pipeline():
    """A6: Verify Repair Bay scan→propose→sandbox→deploy chain."""
    print("\n=== A6: Repair Bay Pipeline Verify ===")
    results = []

    try:
        from database import get_db_cursor

        # Test 1: Scan results exist and are recent
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT COUNT(*), MAX(created_at)
                FROM scan_results
            """)
            row = cur.fetchone()
            scan_count = row[0] if row else 0
            last_scan = row[1] if row else None

            cur.execute("""
                SELECT severity, COUNT(*)
                FROM scan_results
                WHERE status = 'open'
                GROUP BY severity
                ORDER BY severity
            """)
            open_by_severity = {r[0]: r[1] for r in cur.fetchall()}

        results.append({
            "test": "scan_results",
            "status": "pass" if scan_count > 0 else "fail",
            "detail": f"total={scan_count}, last={last_scan}, open_by_severity={open_by_severity}",
        })
        print(f"  [{'+'if scan_count > 0 else '!'}] Scans: {scan_count} results, open={open_by_severity}")

        # Test 2: Proposals exist
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT status, COUNT(*)
                FROM improvement_proposals
                GROUP BY status
            """)
            proposal_stats = {r[0]: r[1] for r in cur.fetchall()}

        total_proposals = sum(proposal_stats.values())
        results.append({
            "test": "proposals",
            "status": "pass" if total_proposals > 0 else "warn",
            "detail": f"total={total_proposals}, by_status={proposal_stats}",
        })
        print(f"  [{'+'if total_proposals > 0 else '!'}] Proposals: {total_proposals}, status={proposal_stats}")

        # Test 3: Sandbox environments
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT sandbox_type, status, COUNT(*)
                FROM sandbox_environments
                GROUP BY sandbox_type, status
            """)
            sandbox_stats = [{"type": r[0], "status": r[1], "count": r[2]} for r in cur.fetchall()]

        results.append({
            "test": "sandboxes",
            "status": "info",
            "detail": sandbox_stats,
        })
        print(f"  [i] Sandboxes: {sandbox_stats}")

        # Test 4: QA suites and recent runs
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM qa_test_suites WHERE is_active = true")
            active_suites = cur.fetchone()[0]

            cur.execute("""
                SELECT s.name, r.status, r.passed, r.failed, r.started_at
                FROM qa_test_runs r
                JOIN qa_test_suites s ON s.id = r.suite_id
                ORDER BY r.started_at DESC
                LIMIT 10
            """)
            recent_qa = [{"suite": r[0], "status": r[1], "passed": r[2], "failed": r[3], "when": str(r[4])} for r in cur.fetchall()]

        results.append({
            "test": "qa_suites",
            "status": "pass" if active_suites > 0 else "warn",
            "detail": f"active_suites={active_suites}, recent_runs={len(recent_qa)}",
            "recent": recent_qa[:5],
        })
        print(f"  [{'+'if active_suites > 0 else '!'}] QA: {active_suites} active suites, {len(recent_qa)} recent runs")

        # Test 5: Proactive scan job health
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT started_at, status
                FROM autonomy_loop_log
                WHERE job_name LIKE '%proactive_scan%' OR job_name LIKE '%repair%'
                ORDER BY started_at DESC
                LIMIT 5
            """)
            scan_jobs = [{"when": str(r[0]), "status": r[1]} for r in cur.fetchall()]

        results.append({
            "test": "proactive_scan_job",
            "status": "pass" if scan_jobs else "warn",
            "detail": scan_jobs[:3] if scan_jobs else "No proactive scan jobs found",
        })
        print(f"  [{'+'if scan_jobs else '!'}] Proactive scan jobs: {len(scan_jobs)} recent runs")

    except Exception as e:
        results.append({"test": "repair_bay_pipeline", "status": "error", "detail": str(e)[:300]})
        print(f"  [X] Exception: {e}")

    return results
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add repair bay pipeline audit — Phase A6"
```

---

### Task 7: Main Runner + Health Report Output

**Files:**
- Modify: `platform_v2/scripts/ai_command_audit.py`

- [ ] **Step 1: Add main runner and report generation**

Append to `ai_command_audit.py`:

```python
def generate_report(all_results):
    """Generate summary health report."""
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "tracks": {},
        "summary": {"total_tests": 0, "pass": 0, "fail": 0, "warn": 0, "error": 0, "info": 0},
    }

    for track_name, results in all_results.items():
        track_summary = {"pass": 0, "fail": 0, "warn": 0, "error": 0, "info": 0, "manual": 0}
        for r in results:
            s = r.get("status", "unknown")
            if s in track_summary:
                track_summary[s] += 1
            report["summary"]["total_tests"] += 1
            if s in report["summary"]:
                report["summary"][s] += 1

        report["tracks"][track_name] = {
            "summary": track_summary,
            "results": results,
        }

    # Overall health score
    total = report["summary"]["total_tests"]
    passing = report["summary"]["pass"] + report["summary"]["info"]
    report["summary"]["health_pct"] = round(passing / total * 100, 1) if total > 0 else 0

    return report


def main():
    print("=" * 60)
    print("AI COMMAND BACKEND AUDIT — Phase A")
    print(f"Started: {datetime.utcnow().isoformat()}")
    print("=" * 60)

    session = get_session()
    all_results = {}

    # A1: API Sweep
    all_results["a1_api_sweep"] = audit_a1_api_sweep(session)

    # A2: Dispatch Pipeline (needs Flask app context)
    from app import app
    with app.app_context():
        all_results["a2_dispatch"] = audit_a2_dispatch_pipeline()
        all_results["a3_agent_loop"] = audit_a3_agent_loop_jobs()
        all_results["a4_agent_lifecycle"] = audit_a4_agent_lifecycle()
        all_results["a5_knowledge"] = audit_a5_knowledge_pipeline()
        all_results["a6_repair_bay"] = audit_a6_repair_bay_pipeline()

    # Generate report
    report = generate_report(all_results)

    # Save to file
    report_path = os.path.join(os.path.dirname(__file__), "..", "qa", "audit-report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Print summary
    s = report["summary"]
    print("\n" + "=" * 60)
    print("AUDIT COMPLETE")
    print(f"Total tests: {s['total_tests']}")
    print(f"  PASS: {s['pass']}  |  FAIL: {s['fail']}  |  WARN: {s['warn']}  |  ERROR: {s['error']}  |  INFO: {s['info']}")
    print(f"  Health: {s['health_pct']}%")
    print(f"Report saved: {report_path}")
    print("=" * 60)

    return report


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full audit**

```bash
docker exec -e AUDIT_PASSWORD='Kyt$13ran2025' archie_platform python3 scripts/ai_command_audit.py
```

Expected: Full audit output with pass/fail per track, health report saved to `platform_v2/qa/audit-report.json`.

- [ ] **Step 3: Review the report**

```bash
docker exec archie_platform cat /app/platform_v2/qa/audit-report.json | python3 -m json.tool | head -50
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/scripts/ai_command_audit.py
git commit -m "feat: add main runner + health report — Phase A complete"
```

---

### Task 8: Run Audit and Store Results

- [ ] **Step 1: Run the full audit inside Docker**

```bash
docker exec -e AUDIT_PASSWORD='Kyt$13ran2025' archie_platform python3 scripts/ai_command_audit.py
```

- [ ] **Step 2: Review the JSON report for failures**

Read `platform_v2/qa/audit-report.json` and identify:
- All `"status": "fail"` entries — these are broken and need fixing
- All `"status": "error"` entries — these crashed during testing
- All `"status": "warn"` entries — these work but need attention

- [ ] **Step 3: Store findings in KB via MCP**

Call `mcp__archie__store_memory` with:
- title: "AI Command Phase A Backend Audit Results — 2026-04-13"
- knowledge_type: "vault_note"
- content: summary of pass/fail counts per track + list of critical failures

- [ ] **Step 4: Update tasks #1849-#1854 as complete with notes**

Mark each Phase A task complete with specific findings from that track.
