# Consciousness Module Health Check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit the Consciousness module for bugs and quality issues, browser-test all 5 tabs, migrate loop controls to Autonomy, clean up the UI, and close the audit green.

**Architecture:** Consciousness (5 tabs, 111 routes, 9 services + 7 helpers) gets a full code review, then loop/job controls migrate to the Autonomy module (which already has APScheduler integration). Consciousness keeps read-only status displays and GitHub ingest. Both modules verified working after migration.

**Tech Stack:** Flask Blueprints, JavaScript (vanilla), Playwright (Node.js), PostgreSQL, APScheduler

**Spec:** `docs/superpowers/specs/2026-03-23-consciousness-health-check-design.md`

---

## File Map

### Files to Review (no changes unless bugs found)
- `platform_v2/tools/consciousness/routes.py` (7,592 lines)
- `platform_v2/tools/consciousness/knowledge_routes.py`
- `platform_v2/tools/consciousness/github_routes.py` (80KB)
- `platform_v2/tools/consciousness/insights_routes.py`
- `platform_v2/tools/consciousness/integration_routes.py`
- `platform_v2/tools/consciousness/code_health_routes.py`
- `platform_v2/tools/consciousness/processing_routes.py` (57KB, nested Blueprint)
- `platform_v2/tools/consciousness/claude_bridge.py`
- `platform_v2/tools/consciousness/collaboration_engine.py`
- `platform_v2/tools/consciousness/dependency_scanner.py`
- `platform_v2/tools/consciousness/learning_extractor.py`
- `platform_v2/tools/consciousness/log_ingestor.py`
- `platform_v2/tools/consciousness/memory_service.py`
- `platform_v2/tools/consciousness/voice_pregen.py`
- `platform_v2/static/js/consciousness.js` (3,356 lines)
- `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (126KB)

### Files to Modify
- `platform_v2/tools/consciousness/__init__.py` — remove `startup_resume_loops()`, update action_registry
- `platform_v2/tools/consciousness/processing_routes.py` — extract loop endpoints
- `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` — remove loop UI
- `platform_v2/static/js/consciousness.js` — remove loop control functions
- `platform_v2/tools/autonomy/ops_routes.py` — add per-job toggle endpoints
- `platform_v2/templates/tools/autonomy.html` — add job control cards to Active Jobs tab
- `platform_v2/tools/autonomy/__init__.py` — add `startup_resume_loops()` import

### Files to Delete
- `platform_v2/tools/consciousness/team_routes.py` — dead code, not imported

### Files to Create
- `tests/consciousness_browser_test.js` — Playwright test script (temporary, can delete after)

---

## Task 1: Code Review — Route Files (Parallel)

**Goal:** Find bugs, dead code, security issues across all 7 active route files + 7 helper files.

**Files:** All 14 Python files listed in "Files to Review" above.

- [ ] **Step 1: Dispatch parallel code review agents**

Split into 3 review batches:
- Batch A: `routes.py` + `knowledge_routes.py` + `insights_routes.py` (core routes)
- Batch B: `github_routes.py` + `processing_routes.py` + `code_health_routes.py` + `integration_routes.py` (specialized routes)
- Batch C: All 7 helper files (`claude_bridge.py`, `collaboration_engine.py`, `dependency_scanner.py`, `learning_extractor.py`, `log_ingestor.py`, `memory_service.py`, `voice_pregen.py`)

Review criteria:
- DB connection leaks (missing `conn.close()` in finally blocks)
- Bare `except:` clauses (should be `except Exception:` minimum)
- Missing input validation on user-facing endpoints
- Dead/unreachable code
- Hardcoded credentials or secrets
- SQL injection risks (string formatting in queries vs parameterized)
- Import errors or missing dependencies

- [ ] **Step 2: Collect and triage findings**

Categorize as:
- **CRITICAL**: Security vulnerabilities, data loss risks
- **HIGH**: Bugs that affect functionality, connection leaks
- **MEDIUM**: Dead code, code quality issues
- **LOW**: Style, minor improvements

Present findings to user for approval before fixing.

---

## Task 2: Code Review — Frontend (JS + Template)

**Goal:** Find broken API calls, memory leaks, dead HTML in the frontend.

**Files:**
- `platform_v2/static/js/consciousness.js` (3,356 lines)
- `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (126KB)

- [ ] **Step 1: Review consciousness.js**

Focus areas:
- `setInterval` timers without corresponding `clearInterval` (memory leaks)
- API endpoint URLs that don't match actual route definitions
- Orphaned functions (defined but never called)
- Error handling in `fetch()` calls (missing `.catch()`)
- Global variable pollution

- [ ] **Step 2: Review consciousness_dashboard.html**

Focus areas:
- HTML elements referenced in JS but missing from template
- Dead sections (hidden/commented out blocks)
- Broken `data-tab` references
- Missing CSRF tokens on forms
- Inline scripts that should be in consciousness.js

- [ ] **Step 3: Merge findings with Task 1 triage**

Add frontend findings to the same CRITICAL/HIGH/MEDIUM/LOW list.

---

## Task 3: Browser Test All 5 Tabs

**Goal:** Verify each tab loads, renders data, and has no JS errors.

**Files:**
- Create: `tests/consciousness_browser_test.js`

- [ ] **Step 1: Write Playwright test script**

```javascript
// tests/consciousness_browser_test.js
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', err => errors.push(`[PAGE ERROR] ${err.message}`));

  const BASE = 'http://192.168.1.200:3000';
  const results = {};

  // Login
  await page.goto(`${BASE}/login`);
  // Credentials from env vars (see frontend.md for values)
  await page.fill('input[name="username"]', process.env.ARCHIE_TEST_USER || 'admin');
  await page.fill('input[name="password"]', process.env.ARCHIE_TEST_PASS || '');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard**', { timeout: 10000 });

  // Navigate to Consciousness
  await page.goto(`${BASE}/tools/consciousness`);
  await page.waitForLoadState('networkidle');

  const tabs = ['dashboard', 'knowledge', 'github', 'languages', 'codehealth'];

  for (const tab of tabs) {
    errors.length = 0;
    const tabErrors = [];

    // Click tab
    const btn = await page.$(`button[data-tab="${tab}"]`);
    if (btn) {
      await btn.click();
      await page.waitForTimeout(2000); // Let tab content load
    }

    // Screenshot
    await page.screenshot({ path: `tests/screenshots/consciousness-${tab}.png`, fullPage: true });

    // Check for errors
    tabErrors.push(...errors);

    results[tab] = {
      loaded: btn !== null,
      errors: [...tabErrors],
      status: tabErrors.length === 0 ? 'PASS' : 'WARN'
    };
  }

  // Print results
  console.log(JSON.stringify(results, null, 2));

  await browser.close();
})();
```

- [ ] **Step 2: Create screenshots directory and run test**

```bash
mkdir -p tests/screenshots
cd /mnt/archie_brain && node tests/consciousness_browser_test.js
```

Expected: JSON output with pass/fail per tab + screenshots saved.

- [ ] **Step 3: Review results and add to findings triage**

Check each screenshot visually. Add any broken tabs to findings list.

---

## Task 4: Fix Critical and High Bugs

**Goal:** Fix all CRITICAL and HIGH findings from Tasks 1-3.

**Files:** Depends on findings — determined after triage.

- [ ] **Step 1: Get user approval on which bugs to fix**

Present the triage list. User decides what's in scope for this session.

- [ ] **Step 2: Fix each approved bug**

One commit per logical fix. Run `docker compose restart archie_platform` after each backend change.

- [ ] **Step 3: Delete dead code — team_routes.py**

```bash
git rm platform_v2/tools/consciousness/team_routes.py
git commit -m "chore: remove dead team_routes.py (merged into Starbase Crew tab)"
```

- [ ] **Step 4: Verify fixes**

Re-run browser test on affected tabs. Confirm no regressions.

---

## Task 5: Loop Migration — Extract from Consciousness

**Goal:** Remove loop control endpoints and startup logic from Consciousness.

**Files:**
- Modify: `platform_v2/tools/consciousness/__init__.py`
- Modify: `platform_v2/tools/consciousness/processing_routes.py`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

- [ ] **Step 1: Identify exact loop endpoints and all consumers**

Read `processing_routes.py` and list all `/api/processing/server-loop/*` endpoints:
- `GET /api/processing/server-loop/status`
- `POST /api/processing/server-loop/toggle`
- Any others found

Then **grep the entire codebase** for all references to old URL paths:
```bash
grep -r "api/processing/server-loop" platform_v2/ ai_bridge/ --include="*.py" --include="*.js" --include="*.html"
```
Document all consumers — these must be updated to point at new Autonomy URLs after migration.

These endpoints will be recreated in Autonomy.

- [ ] **Step 2: Remove `startup_resume_loops()` from Consciousness __init__.py**

Remove the import and call. Leave a comment pointing to Autonomy.

```python
# Loop startup moved to Autonomy module (2026-03-23)
# See: tools/autonomy/__init__.py
```

- [ ] **Step 3: Remove loop control UI from template**

In `consciousness_dashboard.html`:
- Remove the Loop Monitor grid section (`id="loopMonitorTerminal"` / `id="loopMonitorGrid"`)
- Remove start/stop buttons from Knowledge, Languages, Code Health tabs
- Keep read-only status displays (embedding coverage %, translation coverage, scan results)

- [ ] **Step 4: Remove loop control functions from consciousness.js**

Remove these functions:
- `_startLoopMonitor()`
- `_stopLoopMonitor()`
- `_syncServerLoop()`
- `_loadLoopState()`
- `_saveLoopState()`
- Any `setInterval` timers for loop status polling

Keep:
- Read-only status fetch functions
- Tab switching logic
- All non-loop API calls

- [ ] **Step 5: Update action_registry entries**

In `__init__.py`, update or remove action_registry entries for migrated controls:
- `consciousness.analysis.start` → will be re-registered by Autonomy
- `consciousness.embeddings.generate` → will be re-registered by Autonomy
- `consciousness.translate.generate` → will be re-registered by Autonomy

Keep:
- `consciousness.github.reindex` (stays in Consciousness)

- [ ] **Step 6: Commit extraction**

```bash
git add -A platform_v2/tools/consciousness/
git add platform_v2/static/js/consciousness.js
git commit -m "refactor: extract loop controls from Consciousness module

Loop endpoints, startup logic, and UI controls moved to Autonomy.
Consciousness retains read-only status displays and GitHub ingest.
Part 1 of loop migration (extraction)."
```

---

## Task 6: Loop Migration — Wire into Autonomy

**Goal:** Add per-job control endpoints and UI to the Autonomy module.

**Files:**
- Create: `platform_v2/services/loop_service.py` (extracted from processing_routes.py)
- Modify: `platform_v2/tools/autonomy/__init__.py`
- Modify: `platform_v2/tools/autonomy/ops_routes.py`
- Modify: `platform_v2/templates/tools/autonomy.html`
- Modify: `platform_v2/tools/consciousness/processing_routes.py` (update imports to use shared service)

- [ ] **Step 1: Extract loop functions to shared service**

Create `platform_v2/services/loop_service.py` containing the loop management functions extracted from `processing_routes.py`:
- `startup_resume_loops()`
- `get_server_loops()`
- `set_server_loop()`
- `server_loop_retrigger()`

This avoids a circular dependency (Autonomy importing from Consciousness). Both modules import from the shared service instead.

Update `processing_routes.py` to import from the new shared location:
```python
from services.loop_service import get_server_loops, set_server_loop, server_loop_retrigger
```

- [ ] **Step 2: Add startup_resume_loops() to Autonomy __init__.py**

```python
# Loop startup (migrated from Consciousness 2026-03-23)
try:
    from services.loop_service import startup_resume_loops
    startup_resume_loops()
except Exception as e:
    print(f"[AUTONOMY] Loop startup failed: {e}")
```

- [ ] **Step 3: Fix local get_db() in ops_routes.py**

Replace the local `get_db()` function (line ~23) and all 4 existing endpoints (`ops_summary`, `ops_active_jobs`, `ops_health`, `ops_history`) to use the shared `database.py` pattern:
```python
from database import get_db_cursor
# Replace: conn = get_db(); ... conn.close()
# With: with get_db_cursor() as (conn, cur):
```

Also update the existing `from tools.consciousness.processing_routes import get_server_loops` import to:
```python
from services.loop_service import get_server_loops
```

- [ ] **Step 4: Add per-job toggle endpoint to ops_routes.py**

Use the shared `database.py` pattern:

```python
@bp.route('/api/ops-active-jobs/<job_id>/toggle', methods=['POST'])
@admin_required
def toggle_job(job_id):
    """Start or stop an individual job."""
    # Implementation depends on APScheduler job management API
    # scheduler.pause_job(job_id) / scheduler.resume_job(job_id)
    pass
```

- [ ] **Step 5: Add server-loop status/toggle endpoints to ops_routes.py**

Mirror the endpoints removed from Consciousness:
- `GET /api/ops-server-loop/status`
- `POST /api/ops-server-loop/toggle`

These wrap the same backend logic (now in `loop_service.py`), just at a new URL.

- [ ] **Step 6: Add job control cards to Autonomy Active Jobs tab**

In `autonomy.html`, enhance the `#tab-active` section:
- Each job gets a card with: name, status badge, last run, next run, start/stop toggle button
- Cards grouped by category: Server Loops, Agent Loop Jobs, Processing Jobs
- Toggle buttons call the new per-job endpoint

- [ ] **Step 7: Register migrated action_registry entries**

In `autonomy/__init__.py`, register:
- `autonomy.loop.toggle` (replaces `consciousness.analysis.start`)
- `autonomy.embeddings.generate` (replaces `consciousness.embeddings.generate`)
- `autonomy.translate.generate` (replaces `consciousness.translate.generate`)

- [ ] **Step 8: Commit wiring**

```bash
git add platform_v2/services/loop_service.py
git add -A platform_v2/tools/autonomy/
git add platform_v2/templates/tools/autonomy.html
git add platform_v2/tools/consciousness/processing_routes.py
git commit -m "feat: wire loop controls into Autonomy module

Extract loop functions to shared services/loop_service.py.
Per-job start/stop/status cards in Active Jobs tab.
Server loop endpoints migrated from Consciousness.
startup_resume_loops() now runs from Autonomy init.
Fix local get_db() in ops_routes.py to use shared database.py.
Part 2 of loop migration (wiring)."
```

---

## Task 7: UI Cleanup

**Goal:** Clean up Consciousness UI after loop removal. Verify both modules.

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

- [ ] **Step 1: Clean up Dashboard tab layout**

With Loop Monitor grid removed, ensure:
- Neural Core visualization and header stats fill the space
- No empty/broken sections
- StationOps panel (ANALYTICS) still renders correctly

- [ ] **Step 2: Clean up Knowledge tab**

With INGEST button removed:
- Embedding coverage bar is read-only display
- No broken onclick handlers referencing removed functions

- [ ] **Step 3: Clean up Languages tab**

With GENERATE/SCAN buttons removed:
- Coverage display is read-only
- No orphaned event listeners

- [ ] **Step 4: Clean up Code Health tab**

With SCAN/BACKFILL buttons removed:
- Results display is read-only
- Audit log still loads

- [ ] **Step 5: Remove orphaned JS**

Grep `consciousness.js` for any remaining references to removed functions or elements. Remove dead code.

- [ ] **Step 6: Commit cleanup**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git add platform_v2/static/js/consciousness.js
git commit -m "chore: clean up Consciousness UI after loop migration

Remove orphaned HTML sections, dead JS functions, and broken
event listeners from loop control removal."
```

---

## Task 8: Verification & Audit Closure

**Goal:** Prove everything works. Close the audit green.

- [ ] **Step 1: Deploy**

```bash
docker compose restart archie_platform
```

Wait for container to be healthy.

- [ ] **Step 2: Re-run browser test on Consciousness**

```bash
node tests/consciousness_browser_test.js
```

All 5 tabs must pass. No JS errors. Screenshots show correct UI.

- [ ] **Step 3: Browser test Autonomy module**

Navigate to http://192.168.1.200:3000/tools/autonomy
- Verify Active Jobs tab shows job cards with controls
- Verify loop toggle works
- Verify per-job start/stop works (if implemented)

- [ ] **Step 4: Verify startup_resume_loops() works**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | grep -i "loop\|resume\|startup"
```

Confirm loops auto-resume after restart.

- [ ] **Step 5: Run Code Health scan**

From Autonomy (or Consciousness read-only display), trigger a code health scan. Verify Consciousness module shows green/healthy.

- [ ] **Step 6: Close audit — MCP calls**

```
mcp complete_task — Task #1283 "Browser-test all 5 Consciousness tabs" with results
mcp complete_task — Task #1284 "Test GitHub ingestion end-to-end" (if tested)
mcp log_decision — "Loop controls migrated from Consciousness to Autonomy" with rationale
mcp update_project_understanding — Project #180
mcp store_memory — Any mistakes learned (type: mistake_learned)
```

- [ ] **Step 7: Keep test artifacts for Project #181**

Keep `tests/consciousness_browser_test.js` and `tests/screenshots/` — these feed into the Claude Playwright Skill project (#181) as reference material. Add to `.gitignore` if not already there:
```bash
echo "tests/screenshots/" >> .gitignore
```

---

## Dependency Chain

```
Task 1 (Code Review Routes) ──┐
Task 2 (Code Review Frontend) ─┤──→ Task 4 (Fix Bugs) ──→ Task 5 (Extract) ──→ Task 6 (Wire) ──→ Task 7 (Cleanup) ──→ Task 8 (Verify)
Task 3 (Browser Test) ─────────┘
```

Tasks 1, 2, and 3 can run **in parallel**. Everything else is sequential.
