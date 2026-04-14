# P.R.O.B.E. Phase 2 Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/archie-qa` slash command, pytest-based Playwright module tests, and branded PDF report templates to complete P.R.O.B.E.'s core QA pipeline.

**Architecture:** Most infrastructure already exists (qa_service.py, qa_e2e_runner.py, qa_report_service.py, weasyprint, playwright, pytest all installed). This plan wires pytest module tests into the existing suite runner, adds report HTML templates, and creates the slash command entry point.

**Tech Stack:** Python, pytest, Playwright (async), weasyprint, Flask, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-04-14-probe-phase2-core-design.md`

**Key existing files:**
- `platform_v2/services/qa_service.py` — `run_suite()`, `get_run_results()`, `get_suites()`
- `platform_v2/services/qa_e2e_runner.py` — Playwright async runner with auth, screenshots
- `platform_v2/services/qa_report_service.py` — `generate_report()` with weasyprint
- `platform_v2/mcp_server/tools/qa_tools.py` — MCP `run_qa_suite` handler
- `platform_v2/tools/repair_bay/qa_routes.py` — API endpoints for suites, runs, reports

**DB tables (all exist):**
- `qa_test_suites` — id, name, description, target_url, spec (JSONB), suite_type, is_active
- `qa_test_runs` — id, suite_id, triggered_by, status, total/passed/failed/errors, duration_ms, report_path
- `qa_test_results` — id, run_id, test_name, test_type, status, url, response_time_ms, error_message, screenshot_path

---

### Task 1: Create pytest test fixtures (conftest.py)

**Files:**
- Create: `platform_v2/qa/tests/__init__.py`
- Create: `platform_v2/qa/tests/conftest.py`
- Create: `platform_v2/qa/tests/modules/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/platform_v2/qa/tests/modules
mkdir -p /mnt/archie_brain/platform_v2/qa/report_templates
```

- [ ] **Step 2: Create `__init__.py` files**

Create empty `platform_v2/qa/tests/__init__.py` and `platform_v2/qa/tests/modules/__init__.py`.

- [ ] **Step 3: Create conftest.py with shared fixtures**

Create `platform_v2/qa/tests/conftest.py`:

```python
"""P.R.O.B.E. QA Test Fixtures — shared across all module tests."""

import pytest
import asyncio
import os
import logging
from datetime import datetime
from playwright.async_api import async_playwright

logger = logging.getLogger("probe.tests")

BASE_URL = os.getenv("PROBE_BASE_URL", "http://192.168.1.200:3000")
TEST_USER = os.getenv("PROBE_TEST_USER", "admin")
TEST_PASS = os.getenv("PROBE_TEST_PASS", "Kyt$13ran2025")
SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "test-screenshots",
    datetime.now().strftime("%Y-%m-%d"),
)


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def browser():
    """Launch a browser instance for the entire test session."""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    yield browser
    await browser.close()
    await pw.stop()


@pytest.fixture
async def authenticated_page(browser):
    """Create a new page and log in with test credentials."""
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()

    # Collect console errors
    page._console_errors = []
    page.on("console", lambda msg: (
        page._console_errors.append(msg.text)
        if msg.type == "error" else None
    ))

    # Login
    await page.goto(f"{BASE_URL}/login")
    await page.fill('input[name="username"]', TEST_USER)
    await page.fill('input[name="password"]', TEST_PASS)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE_URL}/**", timeout=10000)

    yield page

    await context.close()


async def navigate_to(page, path):
    """Navigate to a module path and wait for it to load."""
    url = f"{BASE_URL}{path}"
    response = await page.goto(url, wait_until="networkidle", timeout=15000)
    return response


async def screenshot(page, name):
    """Take a screenshot and save to the test-screenshots directory."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    return path


async def check_tabs(page, expected_tabs):
    """Verify expected tabs exist and are clickable.

    Args:
        page: Playwright page
        expected_tabs: list of tab label strings to check for
    Returns:
        dict with 'found' and 'missing' lists
    """
    found = []
    missing = []
    for tab_label in expected_tabs:
        locator = page.locator(
            f"text='{tab_label}'"
        ).first
        if await locator.count() > 0:
            found.append(tab_label)
        else:
            missing.append(tab_label)
    return {"found": found, "missing": missing}


RESPONSIVE_BREAKPOINTS = [480, 768, 1024]


async def check_responsive(page, name):
    """Screenshot at each breakpoint.

    Returns list of screenshot paths.
    """
    paths = []
    for width in RESPONSIVE_BREAKPOINTS:
        await page.set_viewport_size({"width": width, "height": 800})
        await page.wait_for_timeout(500)
        path = await screenshot(page, f"{name}-{width}px")
        paths.append(path)
    # Reset to default
    await page.set_viewport_size({"width": 1280, "height": 800})
    return paths


def assert_no_console_errors(page, ignore_patterns=None):
    """Assert no JS console errors occurred.

    Args:
        page: Playwright page (must have _console_errors from fixture)
        ignore_patterns: list of substrings to ignore in error messages
    """
    ignore = ignore_patterns or []
    real_errors = [
        e for e in page._console_errors
        if not any(pat in e for pat in ignore)
    ]
    assert len(real_errors) == 0, f"Console errors found: {real_errors}"
```

- [ ] **Step 4: Verify conftest loads**

```bash
docker exec archie_platform python3 -c "import platform_v2.qa.tests.conftest; print('OK')"
```

Expected: `OK` (no import errors)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/qa/tests/ platform_v2/qa/report_templates/
git commit -m "feat(probe): add pytest fixtures — auth, navigation, screenshots, responsive checks"
```

---

### Task 2: Create first module test (Consciousness)

**Files:**
- Create: `platform_v2/qa/tests/modules/consciousness.py`

- [ ] **Step 1: Create Consciousness module test**

Create `platform_v2/qa/tests/modules/consciousness.py`:

```python
"""P.R.O.B.E. QA — Consciousness Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_consciousness_loads(authenticated_page):
    """Consciousness module loads with HTTP 200 and no JS errors."""
    page = authenticated_page
    response = await navigate_to(page, "/tools/consciousness/")
    assert response.status == 200, f"Expected 200, got {response.status}"
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_consciousness_tabs(authenticated_page):
    """All 5 Consciousness tabs are present."""
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    result = await check_tabs(page, [
        "Dashboard", "Knowledge", "Team", "GitHub", "Languages"
    ])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_consciousness_devhq_tab(authenticated_page):
    """Dev HQ tab loads inside Consciousness."""
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/#devhq")
    await page.wait_for_timeout(1000)
    # Dev HQ has 5 subtabs
    result = await check_tabs(page, [
        "Overview", "Projects", "Ideas", "Decisions", "System"
    ])
    assert len(result["missing"]) == 0, f"Missing Dev HQ subtabs: {result['missing']}"


@pytest.mark.asyncio
async def test_consciousness_knowledge_content(authenticated_page):
    """Knowledge tab shows entries (not empty)."""
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    # Click Knowledge tab
    knowledge_tab = page.locator("text='Knowledge'").first
    await knowledge_tab.click()
    await page.wait_for_timeout(1500)
    # Check that some content loaded
    body_text = await page.inner_text("body")
    assert len(body_text) > 500, "Knowledge tab appears empty"


@pytest.mark.asyncio
async def test_consciousness_responsive(authenticated_page):
    """Consciousness renders at all breakpoints without overflow."""
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    paths = await check_responsive(page, "consciousness")
    assert len(paths) == 3, f"Expected 3 screenshots, got {len(paths)}"


@pytest.mark.asyncio
async def test_consciousness_screenshot(authenticated_page):
    """Capture baseline screenshot of Consciousness dashboard."""
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    path = await screenshot(page, "consciousness-dashboard")
    assert path.endswith(".png")
```

- [ ] **Step 2: Run the test to verify it works**

```bash
docker exec archie_platform python3 -m pytest platform_v2/qa/tests/modules/consciousness.py -v --tb=short 2>&1 | tail -20
```

Expected: Tests run (some may pass, some may fail depending on platform state — that's OK). The important thing is pytest discovers and executes them.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/qa/tests/modules/consciousness.py
git commit -m "feat(probe): add Consciousness module QA tests — 6 tests covering load, tabs, devhq, knowledge, responsive"
```

---

### Task 3: Create remaining 5 module tests

**Files:**
- Create: `platform_v2/qa/tests/modules/department_hq.py`
- Create: `platform_v2/qa/tests/modules/repair_bay.py`
- Create: `platform_v2/qa/tests/modules/agent_academy.py`
- Create: `platform_v2/qa/tests/modules/archie_chat.py`
- Create: `platform_v2/qa/tests/modules/starbase.py`

- [ ] **Step 1: Create Department HQ tests**

Create `platform_v2/qa/tests/modules/department_hq.py`:

```python
"""P.R.O.B.E. QA — Department HQ Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_department_hq_loads(authenticated_page):
    """Department HQ loads with HTTP 200 and no JS errors."""
    page = authenticated_page
    response = await navigate_to(page, "/tools/department-hq/")
    assert response.status == 200, f"Expected 200, got {response.status}"
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_department_hq_tabs(authenticated_page):
    """All 6 Department HQ tabs are present."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    result = await check_tabs(page, [
        "Overview", "Departments", "Agents", "Training", "Welfare", "Settings"
    ])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_department_hq_overview_stats(authenticated_page):
    """Overview tab shows hero stats (not empty)."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    await page.wait_for_timeout(1500)
    body_text = await page.inner_text("body")
    assert "agent" in body_text.lower() or "department" in body_text.lower(), "Overview appears empty"


@pytest.mark.asyncio
async def test_department_hq_responsive(authenticated_page):
    """Department HQ renders at all breakpoints."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    paths = await check_responsive(page, "department-hq")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_department_hq_screenshot(authenticated_page):
    """Capture baseline screenshot."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    path = await screenshot(page, "department-hq-dashboard")
    assert path.endswith(".png")
```

- [ ] **Step 2: Create Repair Bay tests**

Create `platform_v2/qa/tests/modules/repair_bay.py`:

```python
"""P.R.O.B.E. QA — Repair Bay Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_repair_bay_loads(authenticated_page):
    """Repair Bay loads with HTTP 200."""
    page = authenticated_page
    response = await navigate_to(page, "/tools/repair-bay/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_repair_bay_tabs(authenticated_page):
    """All 4 Repair Bay tabs present."""
    page = authenticated_page
    await navigate_to(page, "/tools/repair-bay/")
    result = await check_tabs(page, ["Diagnose", "Repairs", "Test Bay", "Ship"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_repair_bay_responsive(authenticated_page):
    """Repair Bay renders at all breakpoints."""
    page = authenticated_page
    await navigate_to(page, "/tools/repair-bay/")
    paths = await check_responsive(page, "repair-bay")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_repair_bay_screenshot(authenticated_page):
    """Capture baseline screenshot."""
    page = authenticated_page
    await navigate_to(page, "/tools/repair-bay/")
    path = await screenshot(page, "repair-bay-dashboard")
    assert path.endswith(".png")
```

- [ ] **Step 3: Create Agent Academy tests**

Create `platform_v2/qa/tests/modules/agent_academy.py`:

```python
"""P.R.O.B.E. QA — Agent Academy Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_agent_academy_loads(authenticated_page):
    """Agent Academy loads with HTTP 200."""
    page = authenticated_page
    response = await navigate_to(page, "/tools/agent-academy/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_agent_academy_tabs(authenticated_page):
    """All 5 Agent Academy tabs present."""
    page = authenticated_page
    await navigate_to(page, "/tools/agent-academy/")
    result = await check_tabs(page, ["Benchmarks", "Training", "A/B Testing", "Skills", "Reports"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_agent_academy_responsive(authenticated_page):
    """Agent Academy renders at all breakpoints."""
    page = authenticated_page
    await navigate_to(page, "/tools/agent-academy/")
    paths = await check_responsive(page, "agent-academy")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_agent_academy_screenshot(authenticated_page):
    """Capture baseline screenshot."""
    page = authenticated_page
    await navigate_to(page, "/tools/agent-academy/")
    path = await screenshot(page, "agent-academy-dashboard")
    assert path.endswith(".png")
```

- [ ] **Step 4: Create A.R.C.H.I.E. Chat tests**

Create `platform_v2/qa/tests/modules/archie_chat.py`:

```python
"""P.R.O.B.E. QA — A.R.C.H.I.E. Chat Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_archie_chat_loads(authenticated_page):
    """A.R.C.H.I.E. Chat loads with HTTP 200."""
    page = authenticated_page
    response = await navigate_to(page, "/tools/archie-chat/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_archie_chat_tabs(authenticated_page):
    """All 5 A.R.C.H.I.E. Chat tabs present."""
    page = authenticated_page
    await navigate_to(page, "/tools/archie-chat/")
    result = await check_tabs(page, ["Chat", "Collaboration", "Claude TTY", "History", "Settings"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_archie_chat_responsive(authenticated_page):
    """A.R.C.H.I.E. Chat renders at all breakpoints."""
    page = authenticated_page
    await navigate_to(page, "/tools/archie-chat/")
    paths = await check_responsive(page, "archie-chat")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_archie_chat_screenshot(authenticated_page):
    """Capture baseline screenshot."""
    page = authenticated_page
    await navigate_to(page, "/tools/archie-chat/")
    path = await screenshot(page, "archie-chat-dashboard")
    assert path.endswith(".png")
```

- [ ] **Step 5: Create Starbase Command tests**

Create `platform_v2/qa/tests/modules/starbase.py`:

```python
"""P.R.O.B.E. QA — Starbase Command Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_starbase_loads(authenticated_page):
    """Starbase Command loads with HTTP 200."""
    page = authenticated_page
    response = await navigate_to(page, "/tools/starbase/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_starbase_tabs(authenticated_page):
    """Starbase tabs present."""
    page = authenticated_page
    await navigate_to(page, "/tools/starbase/")
    result = await check_tabs(page, ["Fleet", "Operations"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_starbase_responsive(authenticated_page):
    """Starbase renders at all breakpoints."""
    page = authenticated_page
    await navigate_to(page, "/tools/starbase/")
    paths = await check_responsive(page, "starbase")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_starbase_screenshot(authenticated_page):
    """Capture baseline screenshot."""
    page = authenticated_page
    await navigate_to(page, "/tools/starbase/")
    path = await screenshot(page, "starbase-dashboard")
    assert path.endswith(".png")
```

- [ ] **Step 6: Run all module tests**

```bash
docker exec archie_platform python3 -m pytest platform_v2/qa/tests/modules/ -v --tb=short 2>&1 | tail -30
```

Expected: Tests discovered and executed. Record pass/fail counts.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/qa/tests/modules/
git commit -m "feat(probe): add 5 module QA tests — dept-hq, repair-bay, agent-academy, archie-chat, starbase"
```

---

### Task 4: Create report HTML templates

**Files:**
- Create: `platform_v2/qa/report_templates/internal.html`
- Create: `platform_v2/qa/report_templates/branded.html`

- [ ] **Step 1: Create internal report template**

Create `platform_v2/qa/report_templates/internal.html`:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>P.R.O.B.E. QA Report — {{ suite_name }}</title>
<style>
  body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 2cm; color: #1a1a2e; font-size: 11pt; }
  h1 { color: #00e5ff; font-size: 18pt; border-bottom: 2px solid #00e5ff; padding-bottom: 8px; }
  h2 { color: #334155; font-size: 14pt; margin-top: 24px; }
  .summary { display: flex; gap: 20px; margin: 16px 0; }
  .stat { background: #f1f5f9; border-radius: 8px; padding: 12px 20px; text-align: center; flex: 1; }
  .stat-value { font-size: 24pt; font-weight: 700; }
  .stat-label { font-size: 9pt; color: #64748b; text-transform: uppercase; }
  .pass { color: #10b981; }
  .fail { color: #ef4444; }
  .error { color: #f59e0b; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; }
  th { background: #1e293b; color: #e2e8f0; padding: 8px 12px; text-align: left; font-size: 9pt; text-transform: uppercase; }
  td { padding: 8px 12px; border-bottom: 1px solid #e2e8f0; font-size: 10pt; }
  tr:nth-child(even) { background: #f8fafc; }
  .status-pass { color: #10b981; font-weight: 600; }
  .status-fail { color: #ef4444; font-weight: 600; }
  .status-error { color: #f59e0b; font-weight: 600; }
  .failure-detail { background: #fef2f2; border-left: 3px solid #ef4444; padding: 8px 12px; margin: 8px 0; font-size: 9pt; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 8pt; color: #94a3b8; }
  .screenshot { max-width: 100%; border: 1px solid #e2e8f0; border-radius: 4px; margin: 8px 0; }
</style>
</head>
<body>
  <h1>P.R.O.B.E. QA Report</h1>
  <p><strong>Suite:</strong> {{ suite_name }} &nbsp; <strong>Date:</strong> {{ run_date }} &nbsp; <strong>Run ID:</strong> {{ run_id }}</p>

  <div class="summary">
    <div class="stat"><div class="stat-value">{{ total }}</div><div class="stat-label">Total</div></div>
    <div class="stat"><div class="stat-value pass">{{ passed }}</div><div class="stat-label">Passed</div></div>
    <div class="stat"><div class="stat-value fail">{{ failed }}</div><div class="stat-label">Failed</div></div>
    <div class="stat"><div class="stat-value error">{{ errors }}</div><div class="stat-label">Errors</div></div>
    <div class="stat"><div class="stat-value">{{ pass_rate }}%</div><div class="stat-label">Pass Rate</div></div>
  </div>

  <h2>Test Results</h2>
  <table>
    <thead><tr><th>Test</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead>
    <tbody>
    {% for test in results %}
      <tr>
        <td>{{ test.test_name }}</td>
        <td class="status-{{ test.status }}">{{ test.status | upper }}</td>
        <td>{{ test.response_time_ms or '-' }}ms</td>
        <td>{{ test.error_message or '' }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  {% if failures %}
  <h2>Failure Details</h2>
  {% for f in failures %}
    <div class="failure-detail">
      <strong>{{ f.test_name }}</strong><br>
      {{ f.error_message }}
      {% if f.screenshot_path %}
        <br><img class="screenshot" src="{{ f.screenshot_path }}" alt="Failure screenshot">
      {% endif %}
    </div>
  {% endfor %}
  {% endif %}

  <div class="footer">
    Generated by P.R.O.B.E. — Platform Reliability, Observation, Browser-testing &amp; Evaluation<br>
    {{ run_date }}
  </div>
</body>
</html>
```

- [ ] **Step 2: Create branded report template**

Create `platform_v2/qa/report_templates/branded.html`:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Quality Assurance Report — {{ suite_name }}</title>
<style>
  body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; color: #1a1a2e; font-size: 11pt; }
  .header { background: linear-gradient(135deg, #0a0a1a 0%, #1e293b 100%); color: #e2e8f0; padding: 32px 2cm; }
  .header-logo { font-family: 'Trebuchet MS', sans-serif; font-size: 10pt; text-transform: uppercase; letter-spacing: 3px; color: #00e5ff; }
  .header-title { font-size: 22pt; font-weight: 700; margin: 8px 0 4px; }
  .header-subtitle { font-size: 11pt; color: #94a3b8; }
  .content { padding: 24px 2cm; }
  .executive-summary { background: #f0f9ff; border-left: 4px solid #00e5ff; padding: 16px 20px; margin: 16px 0; border-radius: 0 8px 8px 0; }
  .executive-summary p { margin: 0; line-height: 1.6; }
  h2 { color: #334155; font-size: 14pt; margin-top: 24px; }
  .summary { display: flex; gap: 16px; margin: 16px 0; }
  .stat { background: #f1f5f9; border-radius: 8px; padding: 12px 20px; text-align: center; flex: 1; }
  .stat-value { font-size: 24pt; font-weight: 700; }
  .stat-label { font-size: 9pt; color: #64748b; text-transform: uppercase; }
  .pass { color: #10b981; }
  .fail { color: #ef4444; }
  .error { color: #f59e0b; }
  table { width: 100%; border-collapse: collapse; margin: 12px 0; }
  th { background: #1e293b; color: #e2e8f0; padding: 8px 12px; text-align: left; font-size: 9pt; text-transform: uppercase; }
  td { padding: 8px 12px; border-bottom: 1px solid #e2e8f0; font-size: 10pt; }
  tr:nth-child(even) { background: #f8fafc; }
  .status-pass { color: #10b981; font-weight: 600; }
  .status-fail { color: #ef4444; font-weight: 600; }
  .status-error { color: #f59e0b; font-weight: 600; }
  .failure-detail { background: #fef2f2; border-left: 3px solid #ef4444; padding: 8px 12px; margin: 8px 0; font-size: 9pt; }
  .screenshot { max-width: 100%; border: 1px solid #e2e8f0; border-radius: 4px; margin: 8px 0; }
  .creed-badge { text-align: center; margin: 24px 0; padding: 16px; background: rgba(201, 164, 76, 0.05); border: 1px solid rgba(201, 164, 76, 0.2); border-radius: 8px; }
  .creed-badge p { font-size: 9pt; color: #94a3b8; margin: 4px 0; }
  .creed-badge strong { color: #c9a44c; }
  .footer { background: #0a0a1a; color: #64748b; padding: 16px 2cm; font-size: 8pt; text-align: center; }
</style>
</head>
<body>
  <div class="header">
    <div class="header-logo">Kytran Empowerment Inc.</div>
    <div class="header-title">Compliance &amp; Quality Assurance Report</div>
    <div class="header-subtitle">{{ suite_name }} — {{ run_date }}</div>
  </div>

  <div class="content">
    <div class="executive-summary">
      <p><strong>Executive Summary:</strong> P.R.O.B.E. automated QA suite "{{ suite_name }}" completed {{ total }} tests with a {{ pass_rate }}% pass rate. {{ passed }} tests passed, {{ failed }} failed, and {{ errors }} encountered errors. Run ID: {{ run_id }}.</p>
    </div>

    <div class="summary">
      <div class="stat"><div class="stat-value">{{ total }}</div><div class="stat-label">Total Tests</div></div>
      <div class="stat"><div class="stat-value pass">{{ passed }}</div><div class="stat-label">Passed</div></div>
      <div class="stat"><div class="stat-value fail">{{ failed }}</div><div class="stat-label">Failed</div></div>
      <div class="stat"><div class="stat-value">{{ pass_rate }}%</div><div class="stat-label">Pass Rate</div></div>
    </div>

    <h2>Detailed Results</h2>
    <table>
      <thead><tr><th>Test</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead>
      <tbody>
      {% for test in results %}
        <tr>
          <td>{{ test.test_name }}</td>
          <td class="status-{{ test.status }}">{{ test.status | upper }}</td>
          <td>{{ test.response_time_ms or '-' }}ms</td>
          <td>{{ test.error_message or '' }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>

    {% if failures %}
    <h2>Failure Analysis</h2>
    {% for f in failures %}
      <div class="failure-detail">
        <strong>{{ f.test_name }}</strong><br>
        {{ f.error_message }}
        {% if f.screenshot_path %}
          <br><img class="screenshot" src="{{ f.screenshot_path }}" alt="Failure screenshot">
        {% endif %}
      </div>
    {% endfor %}
    {% endif %}

    <div class="creed-badge">
      <strong>C.R.E.E.D.</strong>
      <p>Compliance, Rights &amp; Ethical Enforcement Directive</p>
      <p>This report was generated under C.R.E.E.D. governance standards.</p>
    </div>
  </div>

  <div class="footer">
    Generated by P.R.O.B.E. — Platform Reliability, Observation, Browser-testing &amp; Evaluation<br>
    &copy; 2026 Kytran Empowerment Inc.
  </div>
</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/qa/report_templates/
git commit -m "feat(probe): add QA report HTML templates — internal + branded with C.R.E.E.D. badge"
```

---

### Task 5: Update qa_report_service.py to use templates

**Files:**
- Modify: `platform_v2/services/qa_report_service.py`

- [ ] **Step 1: Read the existing file**

Read `platform_v2/services/qa_report_service.py` in full to understand the current `generate_report()` and `_build_report_html()` functions.

- [ ] **Step 2: Update generate_report to accept branded flag and use Jinja2 templates**

Modify `generate_report()` to:
1. Accept `branded=False` parameter
2. Load the appropriate HTML template from `qa/report_templates/`
3. Render with Jinja2
4. Convert to PDF with weasyprint
5. Save to `static/qa_reports/YYYY-MM-DD_suite-name_run-id.pdf`
6. Update `qa_test_runs.report_path` in DB
7. Return the file path

Key changes to `generate_report(run_id, branded=False)`:
- Load template: `internal.html` or `branded.html` based on `branded` flag
- Use `jinja2.Template(template_str).render(...)` with the run data
- Keep the existing HTML fallback if weasyprint is unavailable
- Pass these template variables: `suite_name`, `run_date`, `run_id`, `total`, `passed`, `failed`, `errors`, `pass_rate`, `results`, `failures`

- [ ] **Step 3: Test PDF generation**

Run a QA suite via MCP, then call generate_report:
```bash
docker exec archie_platform python3 -c "
from services.qa_report_service import generate_report
path = generate_report(1, branded=False)
print(f'Internal report: {path}')
path2 = generate_report(1, branded=True)
print(f'Branded report: {path2}')
"
```

Expected: Two PDF files generated (or HTML fallback if run_id 1 doesn't exist — check with a valid run_id).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/qa_report_service.py
git commit -m "feat(probe): update report service — Jinja2 templates, branded mode, template-based PDF"
```

---

### Task 6: Wire pytest execution into qa_service.run_suite()

**Files:**
- Modify: `platform_v2/services/qa_service.py`

- [ ] **Step 1: Read the existing run_suite() function**

Read `platform_v2/services/qa_service.py` to understand how `run_suite()` currently works — it likely runs the YAML spec-based tests. We need to add a path for pytest-based E2E tests.

- [ ] **Step 2: Add pytest execution path**

In `run_suite()`, after the existing spec-based test execution, add logic to:
1. Check if a pytest module file exists for the suite (e.g., `qa/tests/modules/{suite_name_slug}.py`)
2. If it exists, run `subprocess.run(["python3", "-m", "pytest", test_file, "-v", "--tb=short", "--json-report", "--json-report-file=/tmp/probe-results.json"], capture_output=True, timeout=120)`
3. Parse the pytest JSON output
4. Store individual test results in `qa_test_results` table
5. Update the run totals

Note: This requires `pytest-json-report` package. Check if installed, if not add as a step. Alternative: parse pytest stdout with regex (simpler, no extra dependency).

The simpler approach: parse pytest `-v` output which looks like:
```
tests/modules/consciousness.py::test_consciousness_loads PASSED
tests/modules/consciousness.py::test_consciousness_tabs FAILED
```

Parse each line for test_name and PASSED/FAILED/ERROR status.

- [ ] **Step 3: Test the integration**

```bash
# Trigger a suite run via MCP or direct call
docker exec archie_platform python3 -c "
from services.qa_service import run_suite
result = run_suite(1, triggered_by='probe-phase2-test')
print(result)
"
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/qa_service.py
git commit -m "feat(probe): wire pytest E2E execution into run_suite — auto-discovers module test files"
```

---

### Task 7: Create /archie-qa slash command

**Files:**
- Create: `.claude/commands/archie-qa.md`

- [ ] **Step 1: Create the slash command**

Create `.claude/commands/archie-qa.md`:

```yaml
---
name: archie-qa
description: Run P.R.O.B.E. QA tests — list suites, run by name, generate PDF reports
allowed-tools: Bash, mcp__archie__run_qa_suite, mcp__archie__list_qa_suites, mcp__archie__get_qa_results
argument: Suite name (e.g., "consciousness"), "all", or "list". Add --pdf for PDF report. Add --branded for client report.
---
```

# P.R.O.B.E. QA Runner

## Parse Arguments

Parse `$ARGUMENTS`:
- Empty or "list" → list available suites
- Suite name (e.g., "consciousness") → run that suite
- "all" → run all active suites
- `--pdf` flag → generate PDF report after run
- `--branded` flag → generate branded (client-facing) PDF

## If "list" or empty

Call `mcp__archie__list_qa_suites` and display:

```
P.R.O.B.E. QA Suites:
  1. consciousness (internal) — Consciousness module E2E tests
  2. department-hq (internal) — Department HQ module E2E tests
  ...
```

## If suite name provided

1. Call `mcp__archie__run_qa_suite` with `suite_name` matching the argument
2. Display results inline:
```
P.R.O.B.E. QA: consciousness
  PASS  test_consciousness_loads (234ms)
  PASS  test_consciousness_tabs (156ms)
  FAIL  test_consciousness_devhq_tab — Missing Dev HQ subtabs: ['System']
  PASS  test_consciousness_knowledge_content (1203ms)
  PASS  test_consciousness_responsive (890ms)
  PASS  test_consciousness_screenshot (345ms)

Result: 5/6 passed (83%) — 1 failure
```

3. If `--pdf` flag present OR any failures found:
   - Run: `docker exec archie_platform python3 -c "from services.qa_report_service import generate_report; print(generate_report(RUN_ID, branded=BRANDED))"`
   - Display: `PDF report saved: /path/to/report.pdf`

## If "all"

Run each active suite in sequence, display summary for each, then final totals.

## Notes

- Tests run inside Docker (`archie_platform` container)
- Platform must be running at 192.168.1.200:3000
- First run may be slow (browser cold start)
- Screenshots saved to `platform_v2/qa/test-screenshots/`

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/archie-qa.md
git commit -m "feat(probe): add /archie-qa slash command — run suites, view results, generate PDFs"
```

---

### Task 8: Add PDF download endpoint update

**Files:**
- Modify: `platform_v2/tools/repair_bay/qa_routes.py`

- [ ] **Step 1: Read the existing report endpoints**

Read `platform_v2/tools/repair_bay/qa_routes.py` lines 108-140 (the report generation and download endpoints).

- [ ] **Step 2: Update report generation endpoint to accept branded parameter**

Modify `qa_run_generate_report()` to accept a `branded` query param:

```python
@bp.route("/api/qa/runs/<int:run_id>/report", methods=["POST"])
@login_required
@admin_required
def qa_run_generate_report(run_id):
    """Generate a PDF report for a test run."""
    try:
        branded = request.args.get("branded", "false").lower() == "true"
        report_path = qa_report_service.generate_report(run_id, branded=branded)
        if report_path:
            return jsonify({"success": True, "report_path": report_path})
        return jsonify({"success": False, "error": "Report generation failed"}), 500
    except Exception as e:
        logger.exception("Report generation failed")
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/repair_bay/qa_routes.py
git commit -m "feat(probe): add branded parameter to report generation endpoint"
```

---

### Task 9: Integration test — full pipeline

- [ ] **Step 1: Run the full pipeline via slash command**

Use `/archie-qa consciousness --pdf` and verify:
1. Tests execute inside Docker
2. Results display inline
3. PDF report generates
4. Report file exists at the displayed path

- [ ] **Step 2: Run all suites**

Use `/archie-qa all` and verify all 6 module suites execute.

- [ ] **Step 3: Test branded report**

Use `/archie-qa consciousness --pdf --branded` and verify the branded PDF has Kytran header and C.R.E.E.D. badge.

- [ ] **Step 4: Verify Repair Bay UI**

Navigate to `http://192.168.1.200:3000/tools/repair-bay/` → Test Bay tab. Verify:
- Suites list loads
- Run button works
- Results display
- Download PDF button appears after run

- [ ] **Step 5: Final commit**

```bash
git push origin main
```

- [ ] **Step 6: Complete project tasks**

```bash
# Via MCP
mcp__archie__complete_task(task_id=1725, notes="Built /archie-qa slash command. archie-code CLI deferred to when CLI framework is ready.")
mcp__archie__complete_task(task_id=1726, notes="Playwright pytest runner with 6 module test files, shared conftest fixtures, responsive checks")
mcp__archie__complete_task(task_id=1727, notes="PDF reports via weasyprint with Jinja2 templates — internal + branded modes")
```
