# P.R.O.B.E. Phase 2 Core — Design Spec

> **Goal:** Add a slash command entry point, real Playwright test scripts, and PDF report generation to the existing P.R.O.B.E. QA infrastructure. Make P.R.O.B.E. usable for internal platform QA from Claude Code sessions.

**Scope:** Core infrastructure only (CLI + Playwright + PDF). QA-as-a-Service and full 46-module coverage are deferred to Phase 2B.

**Existing infrastructure:**
- MCP `run_qa_suite` tool (working)
- Bridge dispatch registration for P.R.O.B.E. (working)
- Repair Bay QA tab with routes (`tools/repair_bay/qa_routes.py`)
- `mcp_server/tools/qa_tools.py` — suite execution handler
- `qa_test_suites` and `qa_test_results` DB tables
- 5 QA suites defined for AI Command modules

---

## 1. Architecture

Three new layers on top of existing QA infrastructure:

1. **Slash command (`/archie-qa`)** — Entry point for Claude Code sessions. Calls MCP `run_qa_suite`, displays results, optionally generates PDF.
2. **Playwright test runner** — Python test scripts in `platform_v2/qa/tests/modules/` with shared fixtures. Executed via `pytest` inside Docker. Results stored in existing DB tables.
3. **PDF report generator** — `platform_v2/services/qa_report_service.py` using weasyprint. Two modes: internal (quick summary) and branded (client-ready).

### Data Flow

```
/archie-qa "consciousness"
  -> MCP run_qa_suite
    -> qa_service.run_suite()
      -> subprocess: pytest qa/tests/modules/consciousness.py
      -> results -> qa_test_results table
      -> qa_report_service.generate_pdf()
      -> PDF saved to static/reports/qa/
  -> display summary + PDF path
```

Existing MCP tool and Repair Bay UI continue working unchanged. The slash command is a new entry point only.

---

## 2. Slash Command (`/archie-qa`)

**File:** `.claude/commands/archie-qa.md`

**Usage:**
- `/archie-qa` — list available suites
- `/archie-qa consciousness` — run one suite
- `/archie-qa all` — run all active suites
- `/archie-qa consciousness --pdf` — run and generate PDF report

**Behavior:**
1. Validate suite name against DB (via MCP `list_qa_suites` or inline query)
2. Call `mcp__archie__run_qa_suite` with suite ID
3. Display pass/fail summary inline
4. If `--pdf` flag or failures found, trigger PDF generation
5. Show report path

**Future:** When archie-code CLI is ready, it gets a `qa` subcommand calling the same `/api/qa/run/<suite_id>` HTTP endpoint.

---

## 3. Playwright Test Runner

### Directory Structure

```
platform_v2/qa/
  tests/
    conftest.py              -- shared fixtures
    modules/
      consciousness.py       -- Consciousness module tests
      department_hq.py       -- Department HQ tests
      repair_bay.py          -- Repair Bay tests
      agent_academy.py       -- Agent Academy tests
      archie_chat.py         -- A.R.C.H.I.E. Chat tests
      starbase.py            -- Starbase Command tests
  baseline-screenshots/      -- (existing) golden screenshots
  reports/                   -- generated PDF reports
  report_templates/
    internal.html            -- internal report HTML template
    branded.html             -- client-facing report HTML template
```

### Shared Fixtures (conftest.py)

- `authenticated_page` — logs in with test credentials (`admin` / `Kyt$13ran2025`), returns Playwright page
- `navigate_to(module_path)` — navigates to `http://192.168.1.200:3000{path}` and waits for load
- `screenshot_and_compare(name)` — takes screenshot, optionally compares to baseline
- `check_tabs(expected_tabs)` — verifies all tabs exist and are clickable
- `check_responsive(breakpoints)` — resizes and screenshots at 480/768/1024px
- `assert_no_console_errors()` — checks browser console for JS errors

### Each Module Test Covers

- Page loads (HTTP 200, no JS errors in console)
- All tabs render and switch correctly
- Key data elements present (not empty divs)
- Responsive at 3 breakpoints (480/768/1024px)
- No broken images or missing assets

### Execution

```bash
# Inside Docker container
pytest platform_v2/qa/tests/modules/ -v --tb=short
# Single module
pytest platform_v2/qa/tests/modules/consciousness.py -v
```

The QA service wraps this in `subprocess.run()`, captures stdout, parses pytest output, stores individual test results in `qa_test_results` table.

### Starting Coverage

6 modules (AI Command category — already have suite definitions):
1. Consciousness
2. Department HQ
3. Repair Bay
4. Agent Academy
5. A.R.C.H.I.E. Chat
6. Starbase Command

More modules added incrementally in Phase 2B.

---

## 4. PDF Report Generator

**File:** `platform_v2/services/qa_report_service.py`

### Two Modes

**Internal report** (default, `branded=False`):
- Title, date, suite name
- Pass/fail summary table (test name, status, duration)
- Failure details with error messages
- Screenshots of failures (embedded as base64 images)
- Total pass rate percentage
- Simple clean layout

**Branded report** (`branded=True`):
- Kytran Empowerment header with logo
- "Compliance & Quality Assurance Report" title
- Executive summary paragraph
- Same pass/fail data, client-formatted
- C.R.E.E.D. governance badge at bottom
- "Generated by P.R.O.B.E. — Platform Reliability, Observation, Browser-testing & Evaluation"

### Tech

- weasyprint for HTML-to-PDF conversion
- HTML templates in `platform_v2/qa/report_templates/`
- `internal.html` — clean minimal layout
- `branded.html` — Kytran branding, logo, colors

### Storage

`platform_v2/static/reports/qa/YYYY-MM-DD_suite-name_run-id.pdf`

### Integration

- QA service calls `qa_report_service.generate_report(run_id, branded=False)` after suite run
- Repair Bay UI gets "Download PDF" button on run results
- MCP tool returns PDF path in response
- Slash command shows path to user

---

## 5. Dependencies

- `playwright` Python package (needs install in Docker + `playwright install chromium`)
- `pytest` + `pytest-playwright` (test runner)
- `weasyprint` (HTML-to-PDF, needs system deps: `libpango`, `libcairo`)
- Dockerfile update to install system deps + Python packages

---

## 6. Files to Create/Modify

### Create
- `.claude/commands/archie-qa.md` — slash command
- `platform_v2/qa/tests/conftest.py` — shared test fixtures
- `platform_v2/qa/tests/modules/consciousness.py` — first module tests
- `platform_v2/qa/tests/modules/department_hq.py`
- `platform_v2/qa/tests/modules/repair_bay.py`
- `platform_v2/qa/tests/modules/agent_academy.py`
- `platform_v2/qa/tests/modules/archie_chat.py`
- `platform_v2/qa/tests/modules/starbase.py`
- `platform_v2/services/qa_report_service.py` — PDF generator
- `platform_v2/qa/report_templates/internal.html` — internal report template
- `platform_v2/qa/report_templates/branded.html` — branded report template

### Modify
- `platform_v2/mcp_server/tools/qa_tools.py` — wire subprocess pytest execution + PDF generation
- `platform_v2/tools/repair_bay/qa_routes.py` — add PDF download endpoint
- `Dockerfile` — install weasyprint system deps, playwright, pytest
- `requirements.txt` or equivalent — add playwright, pytest-playwright, weasyprint
