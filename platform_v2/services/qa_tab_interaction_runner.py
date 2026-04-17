"""P.R.O.B.E. Tab Interaction Runner — click-through checks for tabbed modules.

Automates what a human would do in a UX review of a tabbed page: visit the
page, click each tab in turn, and assert:

  1. No console errors accumulate after the click settles.
  2. No stuck ``Loading...`` placeholder remains visible.
  3. (Optional) an expected selector becomes visible.

YAML test spec::

    - name: ac-tab-interaction
      type: tab_interaction
      path: /tools/account-center/
      tabs:
        - name: users
          selector: 'button:has-text("Users")'
        - name: pending
          selector: 'button:has-text("Pending")'
          expect_visible: '[data-testid="pending-table"]'
      settle_ms: 500
      loading_text: "Loading..."

Emits one result per tab: ``status=pass|fail|error``. Console errors are
collected across the whole session and attributed to whichever tab was
active when they fired.
"""

import logging

from playwright.async_api import async_playwright

logger = logging.getLogger("probe.tab_interaction")

DEFAULT_SETTLE_MS = 500
DEFAULT_LOADING_TEXT = "Loading..."


async def _authenticate(context, base_url, auth):
    if not (auth and auth.get("username") and auth.get("password")):
        return
    page = await context.new_page()
    try:
        await page.goto(f"{base_url}/login", wait_until="networkidle", timeout=10000)
        await page.fill('input[name="username"], #username, input[type="text"]', auth["username"])
        await page.fill('input[name="password"], #password, input[type="password"]', auth["password"])
        await page.click('button[type="submit"], input[type="submit"], .btn-primary')
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception as e:
        logger.warning("tab_interaction auth failed: %s", e)
    finally:
        await page.close()


async def _run_one_test(browser, base_url, auth, test):
    """Run a single tab_interaction test. Returns a list of result dicts."""
    path = test.get("path", "/")
    tabs = test.get("tabs") or []
    settle_ms = int(test.get("settle_ms", DEFAULT_SETTLE_MS))
    loading_text = test.get("loading_text", DEFAULT_LOADING_TEXT)
    name = test.get("name", "tab_interaction")

    if not tabs:
        return [
            {
                "test_name": name,
                "test_type": "tab_interaction",
                "status": "error",
                "error_message": "No tabs configured for tab_interaction test.",
            }
        ]

    context = await browser.new_context()
    await _authenticate(context, base_url, auth)
    page = await context.new_page()

    # Bucket console errors by the tab active when they fire.
    current_tab = {"name": "__load__"}
    error_bucket = {}

    def on_console(msg):
        if msg.type == "error":
            error_bucket.setdefault(current_tab["name"], []).append(msg.text[:200])

    page.on("console", on_console)

    results = []
    try:
        await page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=20000)

        load_errors = error_bucket.get("__load__", [])
        if load_errors:
            results.append(
                {
                    "test_name": f"{name}-page-load",
                    "test_type": "tab_interaction",
                    "url": f"{base_url}{path}",
                    "status": "fail",
                    "error_message": f"Console errors on page load: {load_errors[:3]}",
                    "assertions": {"console_errors": load_errors},
                }
            )
        else:
            results.append(
                {
                    "test_name": f"{name}-page-load",
                    "test_type": "tab_interaction",
                    "url": f"{base_url}{path}",
                    "status": "pass",
                    "assertions": {"console_errors": 0},
                }
            )

        for tab in tabs:
            tab_name = tab.get("name") or tab.get("selector") or "unnamed"
            selector = tab.get("selector")
            expect_visible = tab.get("expect_visible")
            current_tab["name"] = tab_name

            result = {
                "test_name": f"{name}-{tab_name}",
                "test_type": "tab_interaction",
                "url": f"{base_url}{path}",
                "status": "pass",
                "assertions": {"tab": tab_name},
            }

            if not selector:
                result["status"] = "error"
                result["error_message"] = f"Tab '{tab_name}' has no selector."
                results.append(result)
                continue

            try:
                await page.click(selector, timeout=5000)
                await page.wait_for_timeout(settle_ms)
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
            except Exception as e:
                result["status"] = "error"
                result["error_message"] = f"Could not click '{selector}': {str(e)[:200]}"
                results.append(result)
                continue

            errors = error_bucket.get(tab_name, [])
            still_loading = False
            try:
                loader = page.get_by_text(loading_text).first
                still_loading = await loader.is_visible(timeout=500)
            except Exception:
                still_loading = False

            expect_ok = True
            if expect_visible:
                try:
                    await page.wait_for_selector(expect_visible, state="visible", timeout=2000)
                except Exception:
                    expect_ok = False

            failures = []
            if errors:
                failures.append(f"{len(errors)} console error(s)")
            if still_loading:
                failures.append(f"'{loading_text}' still visible")
            if not expect_ok:
                failures.append(f"expected selector '{expect_visible}' not visible")

            if failures:
                result["status"] = "fail"
                result["error_message"] = "; ".join(failures)
                result["assertions"] = {
                    "tab": tab_name,
                    "console_errors": errors[:5],
                    "still_loading": still_loading,
                    "expect_visible": expect_visible,
                    "expect_ok": expect_ok,
                }
            else:
                result["assertions"] = {
                    "tab": tab_name,
                    "console_errors": 0,
                    "still_loading": False,
                    "expect_visible": expect_visible,
                    "expect_ok": expect_ok,
                }

            results.append(result)
    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await context.close()
        except Exception:
            pass

    return results


async def execute_batch(tests, base_url, auth):
    """Run every tab_interaction test in one browser session."""
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        try:
            all_results = []
            for test in tests:
                try:
                    sub = await _run_one_test(browser, base_url, auth, test)
                except Exception as e:
                    logger.exception("tab_interaction failed for %s", test.get("name"))
                    sub = [
                        {
                            "test_name": test.get("name", "tab_interaction"),
                            "test_type": "tab_interaction",
                            "status": "error",
                            "error_message": f"Runner exception: {str(e)[:300]}",
                        }
                    ]
                all_results.extend(sub)
            return all_results
        finally:
            await browser.close()
    finally:
        await pw.stop()
