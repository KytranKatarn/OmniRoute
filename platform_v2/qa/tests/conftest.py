"""P.R.O.B.E. QA Test Fixtures — shared across all module tests."""

import pytest
import pytest_asyncio
import os
import logging
from datetime import datetime
from playwright.async_api import async_playwright

# Configure pytest-asyncio to auto mode so all async tests/fixtures work
pytestmark = pytest.mark.asyncio

logger = logging.getLogger("probe.tests")

# NOTE: no custom `event_loop` fixture. pytest-asyncio 1.x manages loops via its
# own session/function runners (driven by asyncio_default_*_loop_scope in
# pytest.ini, both pinned to `session` here). Redefining `event_loop` is
# deprecated in 1.x and was ignored — it only added confusion.

BASE_URL = os.getenv("PROBE_BASE_URL", "http://192.168.1.200:3000")
TEST_USER = os.getenv("PROBE_TEST_USER", "probe")
# No hardcoded credential — must be supplied via the PROBE_TEST_PASS env var.
# (Was previously a hardcoded default; removed so the secret never lives in git.)
import os

# Ensure this is set securely in your environment or secure vault.
# Ensure this is set securely in your environment or secure vault.
# TEST_PASS = getpass(prompt='Enter PROBE_TEST_PASS: ')
TEST_PASS = os.getenv("PROBE_TEST_PASS")
SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "test-screenshots",
    datetime.now().strftime("%Y-%m-%d"),
)


@pytest_asyncio.fixture(scope="session")
async def browser():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    yield browser
    await browser.close()
    await pw.stop()


@pytest_asyncio.fixture(scope="session")
async def auth_context(browser):
    """Log in ONCE per pytest session and share the authenticated context.

    Previously `authenticated_page` was function-scoped and re-logged-in for
    every test. A full run is ~30 logins, which trips the platform IP rate
    limit (20 / 15 min) and makes later suites fail with a misleading
    "login failed". One login per session keeps us well under the limit.
    """
    if not TEST_PASS:
        pytest.fail(
            "PROBE_TEST_PASS env var is not set. Authenticated P.R.O.B.E. suites "
            "require it (and optionally PROBE_TEST_USER, default 'probe'). "
            "No password is hardcoded — set it in the runner env / .env.",
            pytrace=False,
        )
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    await page.goto(f"{BASE_URL}/login")
    await page.fill('input[name="username"]', TEST_USER)
    await page.fill('input[name="password"]', TEST_PASS)
    await page.click('button[type="submit"]')
    # A failed login redirects back to /login. Assert we actually left it and
    # fail LOUD with the real reason instead of letting every downstream test
    # fail with a misleading "missing tabs" (status != artifact).
    await page.wait_for_timeout(1500)
    if "/login" in page.url:
        body = (await page.inner_text("body"))[:200].replace("\n", " ")
        pytest.fail(
            f"Login failed for user {TEST_USER!r} — still on /login. "
            f"Check QA_TEST_USER/QA_TEST_PASS. Page said: {body!r}",
            pytrace=False,
        )
    await page.close()
    yield context
    await context.close()


@pytest_asyncio.fixture
async def authenticated_page(auth_context):
    """Fresh page per test, sharing the session's authenticated cookies."""
    page = await auth_context.new_page()
    page._console_errors = []
    page.on("console", lambda msg: (page._console_errors.append(msg.text) if msg.type == "error" else None))
    # Uncaught exceptions surface as "pageerror", NOT "console" — a console-only
    # listener silently misses every TypeError/ReferenceError that kills a render.
    # Real example: wtf-map.js threw "def.label is not a function" from an onResize
    # handler, so it only fired on a viewport transition. A console-only listener saw
    # an empty list and the suite passed.
    page.on("pageerror", lambda exc: page._console_errors.append(f"Uncaught {exc}"))
    yield page
    await page.close()


async def navigate_to(page, path):
    url = f"{BASE_URL}{path}"
    response = await page.goto(url, wait_until="networkidle", timeout=15000)
    return response


async def screenshot(page, name):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    return path


async def check_tabs(page, expected_tabs):
    found = []
    missing = []
    for tab_label in expected_tabs:
        locator = page.locator(f"text='{tab_label}'").first
        if await locator.count() > 0:
            found.append(tab_label)
        else:
            missing.append(tab_label)
    return {"found": found, "missing": missing}


RESPONSIVE_BREAKPOINTS = [480, 768, 1024]


async def check_responsive(page, name):
    paths = []
    for width in RESPONSIVE_BREAKPOINTS:
        await page.set_viewport_size({"width": width, "height": 800})
        await page.wait_for_timeout(500)
        path = await screenshot(page, f"{name}-{width}px")
        paths.append(path)
    await page.set_viewport_size({"width": 1280, "height": 800})
    return paths


def assert_no_console_errors(page, ignore_patterns=None):
    ignore = ignore_patterns or []
    real_errors = [e for e in page._console_errors if not any(pat in e for pat in ignore)]
    assert len(real_errors) == 0, f"Console errors found: {real_errors}"
