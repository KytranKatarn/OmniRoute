# P.R.O.B.E. — Platform Reliability & Operational Baseline Engine

**Date:** 2026-04-09
**Status:** Design Approved
**Project:** QA Testing Agent
**Branch:** feat/qa-testing-agent

---

## 1. Overview

P.R.O.B.E. is an automated QA testing agent that runs full E2E test suites against the A.R.C.H.I.E. platform (and eventually customer websites). It combines `requests` for API testing with headless Playwright for visual/E2E checks, stores results in a dedicated database schema, generates PDF reports, and alerts via Telegram on failures.

**Goals:**
- Reduce manual QA effort and Claude Code token costs
- Catch regressions automatically via scheduled runs
- Provide on-demand QA from the Repair Bay UI
- Build foundation for QA-as-a-Service resale through KBS

**Non-goals (Phase 1):**
- Customer-facing SaaS UI (future)
- AI-powered site crawling for auto-generated specs (future)
- Post-deploy hook trigger (future)

## 2. Agent Definition

| Field | Value |
|-------|-------|
| Name | P.R.O.B.E. |
| Expansion | Platform Reliability & Operational Baseline Engine |
| Department | Engineering & Technology (F.O.R.G.E.) |
| Role | QA Engineer |
| Model | llama3.2:3b |
| Skills | qa_testing, report_generation, failure_analysis |
| Shift State | active |

P.R.O.B.E. handles:
- Running YAML test specs (scheduled + on-demand)
- AI-powered failure classification (regression vs flaky vs infra) via Bridge dispatch
- PDF report generation
- Future: crawling customer sites to auto-generate specs

**All AI inference goes through Bridge dispatch (ADR-013).** Test execution itself (requests + Playwright) is NOT AI — just HTTP calls and browser automation.

## 3. Architecture

```
┌─────────────────────────────────────────────┐
│  UI Layer — Repair Bay "QA" tab             │
│  (run suites, view results, download PDFs)  │
├─────────────────────────────────────────────┤
│  Service Layer — qa_service.py              │
│  ├── qa_spec_runner.py  (YAML → requests/PW)│
│  ├── qa_report_service.py (PDF generation)  │
│  └── crawl_service.py   (future: site crawl)│
├─────────────────────────────────────────────┤
│  Data Layer                                 │
│  ├── qa_test_suites    (suite definitions)  │
│  ├── qa_test_runs      (execution records)  │
│  └── qa_test_results   (per-test outcomes)  │
└─────────────────────────────────────────────┘
```

**Trigger points:**
- **Scheduled:** Agent loop job every 6 hours (configurable)
- **On-demand:** Repair Bay UI button or API call
- **Post-deploy:** Future hook after `docker compose restart`

**Execution flow:**
1. Load YAML spec (from DB or filesystem)
2. `requests` for API tests (status, response shape, auth, timing)
3. Headless Playwright for page loads + E2E flows (screenshots on failure)
4. Results stored in `qa_test_results` with pass/fail/error + response_time_ms
5. On failure: Telegram alert + Bridge dispatch to P.R.O.B.E. for AI failure analysis
6. PDF report generated on demand or after scheduled runs

## 4. Data Model

```sql
-- Suite definitions (YAML specs stored in DB)
CREATE TABLE IF NOT EXISTS qa_test_suites (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    target_url VARCHAR(500),
    spec JSONB NOT NULL,
    suite_type VARCHAR(50) DEFAULT 'internal',
    user_id INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Execution records (one per run)
CREATE TABLE IF NOT EXISTS qa_test_runs (
    id SERIAL PRIMARY KEY,
    suite_id INTEGER REFERENCES qa_test_suites(id),
    triggered_by VARCHAR(100),
    status VARCHAR(20) DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    duration_ms INTEGER,
    report_path VARCHAR(500),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Per-test outcomes
CREATE TABLE IF NOT EXISTS qa_test_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES qa_test_runs(id),
    test_name VARCHAR(255) NOT NULL,
    test_type VARCHAR(50)
        CHECK (test_type IN ('api', 'page_load', 'e2e')),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('pass', 'fail', 'error', 'skip')),
    url VARCHAR(500),
    method VARCHAR(10),
    expected_status INTEGER,
    actual_status INTEGER,
    response_time_ms INTEGER,
    error_message TEXT,
    screenshot_path VARCHAR(500),
    assertions JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_results_run_id ON qa_test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_qa_results_status ON qa_test_results(status);
CREATE INDEX IF NOT EXISTS idx_qa_runs_suite_id ON qa_test_runs(suite_id);
CREATE INDEX IF NOT EXISTS idx_qa_suites_user_id ON qa_test_suites(user_id);
```

Key design choices:
- `user_id` on suites enables SaaS isolation from day one
- JSONB `spec` and `assertions` keep it flexible
- `screenshot_path` only populated on failures (saves disk)
- `report_path` on runs points to generated PDFs

## 5. YAML Test Spec Format

```yaml
suite:
  name: "ARCHIE Platform — Critical Paths"
  base_url: "http://192.168.1.200:3000"
  auth:
    username: "admin"
    password: "${ARCHIE_TEST_PASSWORD}"

tests:
  # API health checks
  - name: "Platform health endpoint"
    type: api
    method: GET
    path: /api/health
    expect:
      status: 200
      json_contains: { "status": "ok" }

  - name: "Dashboard API requires auth"
    type: api
    method: GET
    path: /api/dashboard/stats
    skip_auth: true
    expect:
      status: [302, 401]

  # Page load checks
  - name: "Dashboard loads"
    type: page_load
    path: /dashboard
    expect:
      status: 200
      title_contains: "A.R.C.H.I.E."
      no_js_errors: true
      max_load_ms: 5000

  # Full E2E flow
  - name: "Login Flow"
    type: e2e
    steps:
      - navigate: /login
      - fill: { selector: "#username", value: "admin" }
      - fill: { selector: "#password", value: "${ARCHIE_TEST_PASSWORD}" }
      - click: "#login-btn"
      - wait: { url_contains: "/dashboard", timeout: 5000 }
      - assert: { selector: ".user-name", text_contains: "admin" }
      - screenshot: "login-success"
```

Spec features:
- `${ENV_VAR}` syntax for secrets — never hardcoded
- `expect` block: status codes, JSON shape, title, JS errors, timing
- `e2e` type: step-by-step Playwright commands
- `skip_auth: true` tests unauthenticated access
- Screenshots: explicit (always capture) or automatic (on failure only)

## 6. File Structure

```
platform_v2/services/
  qa_service.py              — orchestrator (run suite, collect results, trigger alerts)
  qa_spec_runner.py          — YAML parser + test executor (requests + Playwright)
  qa_report_service.py       — PDF report generation (weasyprint: HTML→PDF with LCARS styling)

platform_v2/tools/repair_bay/
  qa_routes.py               — API endpoints for QA tab

ai_bridge/
  agent_loop.py              — new job: _run_qa_scheduled() every 6h

specs/qa/
  archie-critical-paths.yaml — initial test suite for our platform

database/migrations/
  XXX_create_qa_tables.sql   — table creation migration
```

## 7. API Endpoints (Repair Bay QA Tab)

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/qa/run/<suite_id> | Trigger a test run |
| GET | /api/qa/runs | List recent runs |
| GET | /api/qa/runs/<run_id> | Run detail with results |
| GET | /api/qa/runs/<run_id>/report | Download PDF report |
| GET | /api/qa/suites | List available suites |
| POST | /api/qa/suites | Create/update suite |

## 8. Repair Bay QA Tab UI

New tab alongside Diagnose, Repairs, Test Bay, Ship:
- **Top:** Suite selector dropdown + "Run Now" button + last run status badge
- **Middle:** Results table — test name, type, status (green/red/yellow), response time, actions (view screenshot)
- **Bottom:** Run history with trend sparkline (pass rate over last 10 runs)
- **PDF download button** per run

## 9. Telegram Alert Format

```
🔴 P.R.O.B.E. QA Alert — 3 failures

Suite: ARCHIE Critical Paths
Passed: 17/20 | Failed: 3
Duration: 12.4s

Failed:
• Login Flow — timeout waiting for /dashboard
• Security Network tab — JS error on load
• DNS API — 500 Internal Server Error

[View in Repair Bay] [Download PDF]
```

On all-pass scheduled runs: no alert (silent success). Configurable to send summary on success if desired.

## 10. Bridge Dispatch Integration (ADR-013)

All AI calls route through Bridge dispatch via Department HQ:

```python
from bridge_dispatcher import dispatch

# Failure analysis
result = dispatch(
    capability='analyze',
    prompt=f"Classify this QA failure: {error_details}. Is this a regression, flaky test, or infrastructure issue?",
    module_id='qa_agent'
)
```

Bridge is ONLY used for:
- Failure analysis — classify failures
- Future: spec generation — crawl site and generate YAML

Test execution (requests + Playwright) does NOT use Bridge.

## 11. Website Agent Count Update

Replace all hardcoded counts across kytranempowerment.com:
- "15+ AI Directors" (was exact count)
- "125+ Agents" (was exact count)

This prevents maintenance overhead when adding new agents like P.R.O.B.E.

## 12. Initial Test Coverage (Phase 1)

Critical paths only (~20 tests):
- Login/logout flow
- Dashboard loads + API endpoints
- Security Network tabs render
- Department HQ loads
- Dev HQ loads
- Key API auth enforcement checks

Expand to all modules (Phase 2, ~150 tests) after engine is proven.

## 13. Dependencies

- `requests` — already installed
- `playwright` — needs `pip install playwright && playwright install chromium`
- `weasyprint` — needs `pip install weasyprint` (for PDF generation)
- `pyyaml` — already installed

## 14. Future: QA-as-a-Service (Phase 3)

Customer flow:
1. Customer enters URL in KBS dashboard
2. P.R.O.B.E. crawls sitemap via AI (Bridge dispatch)
3. AI generates YAML test specs
4. Customer reviews/tweaks specs
5. Scheduled runs execute against customer site
6. PDF reports delivered via email/dashboard
7. Billing via KBS subscription tier
