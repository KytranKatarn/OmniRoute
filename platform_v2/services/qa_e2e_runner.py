"""
P.R.O.B.E. E2E Runner — Playwright browser testing for QA specs.
Phase 2: Replaces the e2e stub in qa_spec_runner.py.
"""

import asyncio
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.path.join("/tmp", "qa_reports", "screenshots")


class E2ERunner:
    """Async Playwright E2E test executor."""

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None

    async def start_browser(self):
        """Launch headless Chromium."""
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        self.page = await self.context.new_page()

    async def close(self):
        """Clean up browser resources."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if hasattr(self, "_pw"):
                await self._pw.stop()
        except Exception as e:
            logger.debug("E2E cleanup error: %s", e)

    async def authenticate(self, base_url, auth):
        """Log in via the login form."""
        if not auth or not auth.get("username"):
            return
        try:
            await self.page.goto(f"{base_url}/login", wait_until="networkidle", timeout=10000)
            await self.page.fill('input[name="username"], #username, input[type="text"]', auth["username"])
            await self.page.fill('input[name="password"], #password, input[type="password"]', auth["password"])
            await self.page.click('button[type="submit"], input[type="submit"], .btn-primary')
            await self.page.wait_for_load_state("networkidle", timeout=10000)
            logger.info("E2E auth complete, URL: %s", self.page.url)
        except Exception as e:
            logger.warning("E2E auth failed: %s", e)

    async def execute_batch(self, tests, base_url, auth, run_id=None):
        """Execute multiple E2E tests reusing the same browser session.

        Launches browser + authenticates ONCE, then runs each test.
        Saves ~3-4s per test on browser startup and avoids tmpfs exhaustion.
        """
        results = []
        try:
            await self.start_browser()
            # Auth once for the batch — skip if first test has skip_auth
            if tests and not tests[0].get("skip_auth", False):
                await self.authenticate(base_url, auth)

            for test in tests:
                result = await self._execute_single(test, base_url, auth, run_id)
                results.append(result)
        finally:
            await self.close()
        return results

    async def _execute_single(self, test, base_url, auth, run_id=None):
        """Run a single test using the existing browser/page. Used by execute_batch."""
        test_name = test.get("name", "unnamed_e2e")
        path = test.get("path", "/")
        actions = test.get("actions", [])
        expect = test.get("expect", {})
        result = {
            "test_name": test_name,
            "test_type": "e2e",
            "url": f"{base_url}{path}",
            "status": "pass",
            "response_time_ms": 0,
            "error_message": None,
            "screenshot_path": None,
            "assertions": {},
        }

        start = time.time()
        try:
            # Navigate (browser already running, auth already done)
            # Use "load" not "networkidle" — heavy pages (Media Studio, DHQ) have
            # persistent polling that prevents networkidle from resolving, crashing
            # the tab on the 5th+ navigation. Element readiness handled by wait_for actions.
            await self.page.goto(f"{base_url}{path}", wait_until="load", timeout=15000)

            # Execute actions
            for action in actions:
                await self._execute_action(action)

            # Run assertions
            result["assertions"] = await self._check_assertions(expect)

            # Check if any assertion failed
            for key, val in result["assertions"].items():
                if val == "fail":
                    result["status"] = "fail"
                    result["error_message"] = f"Assertion failed: {key}"
                    break

            # Screenshot
            if expect.get("screenshot", False):
                result["screenshot_path"] = await self._take_screenshot(test_name, run_id)

            result["response_time_ms"] = int((time.time() - start) * 1000)

            # max_load_ms check
            max_ms = expect.get("max_load_ms")
            if max_ms and result["response_time_ms"] > max_ms:
                result["assertions"]["max_load_ms"] = "fail"
                if result["status"] == "pass":
                    result["status"] = "fail"
                    result["error_message"] = f"Load time {result['response_time_ms']}ms > {max_ms}ms"
            elif max_ms:
                result["assertions"]["max_load_ms"] = "pass"

        except Exception as e:
            result["status"] = "error"
            result["error_message"] = str(e)
            result["response_time_ms"] = int((time.time() - start) * 1000)
            logger.exception("E2E test '%s' error: %s", test_name, e)

        return result

    async def execute(self, test, base_url, auth, run_id=None):
        """Execute a single E2E test spec and return results."""
        test_name = test.get("name", "unnamed_e2e")
        path = test.get("path", "/")
        actions = test.get("actions", [])
        expect = test.get("expect", {})
        result = {
            "test_name": test_name,
            "test_type": "e2e",
            "url": f"{base_url}{path}",
            "status": "pass",
            "response_time_ms": 0,
            "error_message": None,
            "screenshot_path": None,
            "assertions": {},
        }

        start = time.time()
        try:
            await self.start_browser()

            # Auth unless skipped
            if not test.get("skip_auth", False):
                await self.authenticate(base_url, auth)

            # Navigate
            # Use "load" not "networkidle" — heavy pages (Media Studio, DHQ) have
            # persistent polling that prevents networkidle from resolving, crashing
            # the tab on the 5th+ navigation. Element readiness handled by wait_for actions.
            await self.page.goto(f"{base_url}{path}", wait_until="load", timeout=15000)

            # Execute actions
            for action in actions:
                await self._execute_action(action)

            # Run assertions
            result["assertions"] = await self._check_assertions(expect)

            # Check if any assertion failed
            for key, val in result["assertions"].items():
                if val == "fail":
                    result["status"] = "fail"
                    result["error_message"] = f"Assertion failed: {key}"
                    break

            # Screenshot
            if expect.get("screenshot", False):
                result["screenshot_path"] = await self._take_screenshot(test_name, run_id)

            result["response_time_ms"] = int((time.time() - start) * 1000)

            # max_load_ms check
            max_ms = expect.get("max_load_ms")
            if max_ms and result["response_time_ms"] > max_ms:
                result["assertions"]["max_load_ms"] = "fail"
                if result["status"] == "pass":
                    result["status"] = "fail"
                    result["error_message"] = f"Load time {result['response_time_ms']}ms > {max_ms}ms"
            elif max_ms:
                result["assertions"]["max_load_ms"] = "pass"

        except Exception as e:
            result["status"] = "error"
            result["error_message"] = str(e)
            result["response_time_ms"] = int((time.time() - start) * 1000)
            logger.exception("E2E test '%s' error: %s", test_name, e)
        finally:
            await self.close()

        return result

    async def _execute_action(self, action):
        """Execute a single action from the spec."""
        timeout = action.get("timeout", 10000)

        if "click" in action:
            selector = action["click"]
            # Wait for element to exist in DOM
            try:
                await self.page.wait_for_selector(selector, state="attached", timeout=timeout)
            except Exception:
                pass
            # Try Playwright's locator click first (handles auto-waiting,
            # respects visibility, mimics real user interaction).
            # Fall back to JS click if Playwright can't click (element
            # off-screen, overlapped, hidden behind another element).
            try:
                loc = self.page.locator(selector).first
                try:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                await loc.click(timeout=3000)
            except Exception:
                safe_selector = selector.replace("\\", "\\\\").replace("'", "\\'")
                await self.page.evaluate(f"document.querySelector('{safe_selector}')?.click()")
                # Small delay for DOM transitions
                await asyncio.sleep(0.3)
        elif "fill" in action:
            value = self._resolve_env(action.get("value", ""))
            await self.page.fill(action["fill"], value)
        elif "select_option" in action:
            await self.page.select_option(action["select_option"], action.get("value", ""))
        elif "wait_for" in action:
            await self.page.wait_for_selector(action["wait_for"], timeout=timeout)
        elif "press_key" in action:
            await self.page.keyboard.press(action["press_key"])
        elif "scroll_to" in action:
            await self.page.evaluate(f"document.querySelector('{action['scroll_to']}')?.scrollIntoView()")
        elif "screenshot" in action:
            await self._take_screenshot(action.get("screenshot", "action"), None)
        elif "wait" in action:
            await asyncio.sleep(action["wait"] / 1000)

    async def _check_assertions(self, expect):
        """Run all assertions against the current page state."""
        results = {}

        # selector_count: {'.class': 5}
        for selector, count in (expect.get("selector_count") or {}).items():
            try:
                elements = await self.page.query_selector_all(selector)
                actual = len(elements)
                key = f"count_{selector}"
                results[key] = "pass" if actual == count else "fail"
                if results[key] == "fail":
                    logger.info("E2E assertion %s: expected %d, got %d", key, count, actual)
            except Exception:
                results[f"count_{selector}"] = "fail"

        # selector_visible: {'#id': true}
        for selector, expected in (expect.get("selector_visible") or {}).items():
            try:
                el = await self.page.query_selector(selector)
                visible = el is not None and await el.is_visible() if el else False
                results[f"visible_{selector}"] = "pass" if visible == expected else "fail"
            except Exception:
                results[f"visible_{selector}"] = "fail"

        # selector_text: {'#id': 'expected text'}
        for selector, expected_text in (expect.get("selector_text") or {}).items():
            try:
                el = await self.page.query_selector(selector)
                text = await el.inner_text() if el else ""
                results[f"text_{selector}"] = "pass" if expected_text in text else "fail"
            except Exception:
                results[f"text_{selector}"] = "fail"

        # url_contains
        if "url_contains" in expect:
            results["url_contains"] = "pass" if expect["url_contains"] in self.page.url else "fail"

        # title_contains
        if "title_contains" in expect:
            title = await self.page.title()
            results["title_contains"] = "pass" if expect["title_contains"] in title else "fail"

        return results

    async def _take_screenshot(self, test_name, run_id):
        """Take and save a screenshot."""
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", test_name)[:60]
        filename = f"{run_id or 'manual'}_{safe_name}.png"
        filepath = os.path.join(SCREENSHOT_DIR, filename)
        try:
            await self.page.screenshot(path=filepath, full_page=False)
            return f"qa_reports/screenshots/{filename}"
        except Exception as e:
            logger.warning("Screenshot failed: %s", e)
            return None

    @staticmethod
    def _resolve_env(value):
        """Resolve ${ENV_VAR} patterns."""

        def _replace(match):
            return os.getenv(match.group(1), match.group(0))

        return re.sub(r"\$\{(\w+)\}", _replace, value) if "${" in value else value
