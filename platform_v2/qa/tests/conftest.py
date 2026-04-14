"""P.R.O.B.E. QA Test Fixtures — shared across all module tests."""

import pytest
import pytest_asyncio
import asyncio
import os
import logging
from datetime import datetime
from playwright.async_api import async_playwright

# Configure pytest-asyncio to auto mode so all async tests/fixtures work
pytestmark = pytest.mark.asyncio

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
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def browser():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    yield browser
    await browser.close()
    await pw.stop()


@pytest_asyncio.fixture
async def authenticated_page(browser):
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    page._console_errors = []
    page.on("console", lambda msg: (page._console_errors.append(msg.text) if msg.type == "error" else None))
    await page.goto(f"{BASE_URL}/login")
    await page.fill('input[name="username"]', TEST_USER)
    await page.fill('input[name="password"]', TEST_PASS)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{BASE_URL}/**", timeout=10000)
    yield page
    await context.close()


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
