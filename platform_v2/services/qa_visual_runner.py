"""P.R.O.B.E. Visual Snapshot Runner — computed-style + selector snapshot per breakpoint.

Detects LCARS regressions (wrong accent, missing frame class, CSS collisions, responsive
breaks) by serializing ``getComputedStyle()`` output for configured selectors at each
breakpoint and diffing against a stored baseline.

Design doc: docs/superpowers/specs/2026-04-16-probe-capability-upgrade-design.md
Task: #2027 — follow-up to research task #2022.

YAML test spec:

    - name: ac-visual-consistency
      type: visual_snapshot
      path: /tools/account-center/
      breakpoints: [480, 768, 1024]
      selectors:
        - ":root"
        - ".bm-frame"
        - "body"
      snapshot_name: account-center-v1
"""

import logging

from playwright.async_api import async_playwright

logger = logging.getLogger("probe.visual")

# CSS properties to capture for every selector. Deliberately small so the baseline
# stays small and reviewable in diffs.
TRACKED_PROPERTIES = [
    "background-color",
    "color",
    "border-top-color",
    "border-bottom-color",
    "border-style",
    "border-width",
    "font-family",
    "font-size",
    "font-weight",
    "display",
    "position",
]

# CSS custom properties to capture when the selector is :root — the LCARS tokens
# that drive theming. Failures here are the #1 signal we want to catch.
TRACKED_CSS_VARS = [
    "--archie-accent",
    "--archie-bg",
    "--archie-fg",
    "--archie-elbow",
    "--archie-primary",
    "--bm-accent",
    "--lcars-orange",
    "--lcars-blue",
    "--lcars-yellow",
    "--lcars-purple",
]


class VisualRunner:
    """Single-browser runner for visual_snapshot tests. Mirrors E2ERunner shape."""

    def __init__(self):
        self.pw = None
        self.browser = None

    async def start(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    async def _authenticate(self, context, base_url, auth):
        # Mirrors qa_e2e_runner.E2ERunner.authenticate — same fallback selectors.
        if not (auth and auth.get("username") and auth.get("password")):
            return
        page = await context.new_page()
        try:
            await page.goto(f"{base_url}/login", wait_until="networkidle", timeout=10000)
            await page.fill(
                'input[name="username"], #username, input[type="text"]',
                auth["username"],
            )
            await page.fill(
                'input[name="password"], #password, input[type="password"]',
                auth["password"],
            )
            await page.click('button[type="submit"], input[type="submit"], .btn-primary')
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            logger.warning("Visual runner auth failed: %s", e)
        finally:
            await page.close()

    async def _snapshot(self, context, base_url, path, selectors, breakpoint_px, screenshot_name=None, theme=None):
        """Capture CSS computed-style snapshot + optional pixel screenshot.

        Args:
            theme: optional 'light' or 'dark' — injects theme before CSS capture.
                   Uses window.setArchieTheme() if available, falls back to class toggle.

        Returns:
            (css_snap dict, screenshot_relative_path or None)
        """
        import os
        import time as _time

        page = await context.new_page()
        try:
            await page.set_viewport_size({"width": breakpoint_px, "height": 1024})
            await page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=20000)

            if theme:
                await page.evaluate(
                    """(t) => {
                        localStorage.setItem('archie-theme', t);
                        if (typeof window.setArchieTheme === 'function') {
                            window.setArchieTheme(t);
                        } else {
                            if (t === 'light') {
                                document.body.classList.add('light-mode');
                            } else {
                                document.body.classList.remove('light-mode');
                            }
                        }
                    }""",
                    theme,
                )
                await page.wait_for_timeout(400)
            css_snap = await page.evaluate(
                """
                (args) => {
                    const { selectors, trackedProps, trackedVars } = args;
                    const result = {};
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (!el) {
                            result[sel] = { present: false };
                            continue;
                        }
                        const cs = window.getComputedStyle(el);
                        const entry = { present: true, properties: {} };
                        for (const prop of trackedProps) {
                            entry.properties[prop] = cs.getPropertyValue(prop).trim();
                        }
                        if (sel === ':root') {
                            entry.css_vars = {};
                            for (const v of trackedVars) {
                                entry.css_vars[v] = cs.getPropertyValue(v).trim();
                            }
                        }
                        result[sel] = entry;
                    }
                    return result;
                }
                """,
                {
                    "selectors": selectors,
                    "trackedProps": TRACKED_PROPERTIES,
                    "trackedVars": TRACKED_CSS_VARS,
                },
            )

            screenshot_path = None
            if screenshot_name:
                ss_dir = "/tmp/qa_reports/screenshots"
                os.makedirs(ss_dir, exist_ok=True)
                filename = f"{screenshot_name}_{breakpoint_px}_{int(_time.time())}.png"
                filepath = os.path.join(ss_dir, filename)
                await page.screenshot(path=filepath, full_page=True)
                screenshot_path = f"qa_reports/screenshots/{filename}"

            return css_snap, screenshot_path
        finally:
            await page.close()

    async def execute(self, test, base_url, auth, baselines):
        """Run one visual_snapshot test across all configured breakpoints.

        Args:
            test: dict with name, path, breakpoints, selectors, snapshot_name
            baselines: dict keyed by (snapshot_name, breakpoint_int) → baseline JSONB

        Returns:
            list of result dicts (one per breakpoint).
        """
        path = test.get("path", "/")
        selectors = test.get("selectors") or []
        breakpoints = test.get("breakpoints") or [1024]
        snapshot_name = test.get("snapshot_name") or test.get("name")
        name_base = test.get("name", "unnamed_visual")
        theme = test.get("theme")  # optional: 'light' or 'dark'

        if not selectors:
            return [
                {
                    "test_name": name_base,
                    "test_type": "visual_snapshot",
                    "status": "error",
                    "url": f"{base_url}{path}",
                    "error_message": "No selectors provided in spec — nothing to snapshot.",
                }
            ]

        results = []
        context = await self.browser.new_context(ignore_https_errors=True)
        try:
            await self._authenticate(context, base_url, auth)
            for bp in breakpoints:
                test_name = f"{name_base}-bp{bp}"
                url = f"{base_url}{path}"
                ss_name = f"{snapshot_name}-bp{bp}"
                try:
                    snap, screenshot_path = await self._snapshot(
                        context,
                        base_url,
                        path,
                        selectors,
                        int(bp),
                        screenshot_name=ss_name,
                        theme=theme,
                    )
                except Exception as e:
                    results.append(
                        {
                            "test_name": test_name,
                            "test_type": "visual_snapshot",
                            "status": "error",
                            "url": url,
                            "error_message": str(e)[:500],
                        }
                    )
                    continue

                baseline = baselines.get((snapshot_name, int(bp)))
                if baseline is None:
                    # First run — no baseline. Emit skip with current snapshot so
                    # operator can accept it via POST /api/qa/baselines/<suite_id>/accept.
                    results.append(
                        {
                            "test_name": test_name,
                            "test_type": "visual_snapshot",
                            "status": "skip",
                            "url": url,
                            "screenshot_path": screenshot_path,
                            "error_message": (
                                f"No baseline for '{snapshot_name}' @ {bp}px. " "Accept this run to create one."
                            ),
                            "assertions": {
                                "snapshot_name": snapshot_name,
                                "breakpoint": int(bp),
                                "current": snap,
                                "needs_baseline": True,
                            },
                        }
                    )
                    continue

                diffs = diff_snapshots(baseline, snap)
                if not diffs:
                    results.append(
                        {
                            "test_name": test_name,
                            "test_type": "visual_snapshot",
                            "status": "pass",
                            "url": url,
                            "screenshot_path": screenshot_path,
                            "assertions": {
                                "snapshot_name": snapshot_name,
                                "breakpoint": int(bp),
                            },
                        }
                    )
                else:
                    results.append(
                        {
                            "test_name": test_name,
                            "test_type": "visual_snapshot",
                            "status": "fail",
                            "url": url,
                            "screenshot_path": screenshot_path,
                            "error_message": format_diffs(diffs)[:500],
                            "assertions": {
                                "snapshot_name": snapshot_name,
                                "breakpoint": int(bp),
                                "diffs": diffs,
                                "current": snap,
                            },
                        }
                    )
        finally:
            await context.close()

        return results


def diff_snapshots(baseline, current):
    """Return list of diffs — each ``{selector, property, expected, got}``."""
    diffs = []
    baseline = baseline or {}
    current = current or {}
    for sel, base_entry in baseline.items():
        cur_entry = current.get(sel)
        base_present = (base_entry or {}).get("present", False)
        cur_present = (cur_entry or {}).get("present", False) if cur_entry else False

        if base_present and not cur_present:
            diffs.append(
                {
                    "selector": sel,
                    "property": "present",
                    "expected": True,
                    "got": False,
                }
            )
            continue
        if not base_present:
            # Baseline didn't have this selector either — nothing to compare.
            continue

        for prop, expected in (base_entry.get("properties") or {}).items():
            got = (cur_entry.get("properties") or {}).get(prop) if cur_entry else None
            if got != expected:
                diffs.append(
                    {
                        "selector": sel,
                        "property": prop,
                        "expected": expected,
                        "got": got,
                    }
                )

        for var, expected in (base_entry.get("css_vars") or {}).items():
            got = (cur_entry.get("css_vars") or {}).get(var) if cur_entry else None
            if got != expected:
                diffs.append(
                    {
                        "selector": sel,
                        "property": var,
                        "expected": expected,
                        "got": got,
                    }
                )

    return diffs


def format_diffs(diffs):
    """One-line human summary of the first few diffs for error_message fields."""
    if not diffs:
        return ""
    parts = [f"{d['selector']}[{d['property']}] expected '{d['expected']}' got '{d['got']}'" for d in diffs[:5]]
    more = len(diffs) - 5
    if more > 0:
        parts.append(f"...({more} more)")
    return "; ".join(parts)


async def execute_batch(tests, base_url, auth, baselines):
    """Batch entrypoint — one browser for all visual_snapshot tests."""
    runner = VisualRunner()
    await runner.start()
    try:
        all_results = []
        for t in tests:
            results = await runner.execute(t, base_url, auth, baselines)
            all_results.extend(results)
        return all_results
    finally:
        await runner.close()
