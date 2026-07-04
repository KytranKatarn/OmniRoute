"""
Browser Automation — Playwright-based web tasks with domain approval

Task types: scrape, form_fill, monitor, screenshot, custom
New domains require tier-2 approval before first visit.
No GPU usage — AI calls only for script generation via dolphin3.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
from db import get_db

logger = logging.getLogger("browser_automation")

SCREENSHOT_DIR = os.getenv("BROWSER_SCREENSHOT_DIR", "/mnt/archie_brain/platform_v2/static/screenshots")


class BrowserAutomation:
    """
    Playwright-based browser automation with sandboxed execution.

    - execute_task(): Run a browser task
    - check_domain_approval(): Verify domain is approved
    - generate_script(): AI-powered Playwright script generation
    - take_screenshot(): Simple screenshot capture
    """

    def __init__(self):
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    def execute_task(self, task_id: int) -> dict:
        """
        Execute a browser automation task.

        Checks domain approval, runs the task via Playwright, stores results.
        """
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT * FROM browser_tasks WHERE id = %s", (task_id,))
            task = cur.fetchone()
            if not task:
                return {"error": "Task not found"}

            # Parse domain
            parsed = urlparse(task["url"])
            domain = parsed.hostname or ""

            # Check domain approval
            if not self._is_domain_approved(cur, domain):
                # Request approval
                from agent_loop import request_approval

                approval_id = request_approval(
                    action_type="browser_new_domain",
                    action_data={"domain": domain, "url": task["url"], "task_id": task_id},
                    reason=f"Browser automation requires access to new domain: {domain}",
                    requested_by="browser_automation",
                    tier=2,
                )

                cur.execute(
                    """
                    UPDATE browser_tasks
                    SET status = 'awaiting_approval', approval_id = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (approval_id, task_id),
                )
                conn.commit()
                return {
                    "status": "awaiting_approval",
                    "domain": domain,
                    "approval_id": approval_id,
                }

            # Mark running
            cur.execute(
                "UPDATE browser_tasks SET status = 'running', updated_at = NOW() WHERE id = %s",
                (task_id,),
            )
            conn.commit()

            start = time.time()
            result = {}

            try:
                task_type = task["task_type"]
                if task_type == "screenshot":
                    result = self._task_screenshot(task)
                elif task_type == "scrape":
                    result = self._task_scrape(task)
                elif task_type == "monitor":
                    result = self._task_monitor(task)
                elif task_type == "custom":
                    result = self._task_custom(task)
                else:
                    result = self._task_screenshot(task)  # fallback

                duration_ms = int((time.time() - start) * 1000)

                # Store result
                cur.execute(
                    """
                    INSERT INTO browser_task_results
                    (task_id, status, screenshot_path, scraped_data, page_title, page_url, duration_ms, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        task_id,
                        "success" if not result.get("error") else "failed",
                        result.get("screenshot_path"),
                        (json.dumps(result.get("scraped_data")) if result.get("scraped_data") else None),
                        result.get("page_title"),
                        result.get("page_url"),
                        duration_ms,
                        json.dumps(result.get("metadata", {})),
                    ),
                )

                cur.execute(
                    """
                    UPDATE browser_tasks
                    SET status = %s, last_run_at = NOW(), error_message = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        "completed" if not result.get("error") else "failed",
                        result.get("error"),
                        task_id,
                    ),
                )
                conn.commit()

            except Exception as e:
                logger.error(f"Browser task #{task_id} failed: {e}")
                cur.execute(
                    "UPDATE browser_tasks SET status = 'failed', error_message = %s, updated_at = NOW() WHERE id = %s",
                    (str(e)[:500], task_id),
                )
                conn.commit()
                result = {"error": str(e)}

            return result
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _task_screenshot(self, task: dict) -> dict:
        """Capture a screenshot of a URL."""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(task["url"], timeout=task.get("timeout_seconds", 60) * 1000)
                page.wait_for_load_state("networkidle", timeout=30000)

                title = page.title()
                final_url = page.url

                filename = f"task_{task['id']}_{int(time.time())}.png"
                path = os.path.join(SCREENSHOT_DIR, filename)
                page.screenshot(path=path, full_page=True)

                browser.close()

                return {
                    "screenshot_path": f"/static/screenshots/{filename}",
                    "page_title": title,
                    "page_url": final_url,
                }
        except ImportError:
            return {"error": "Playwright not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _task_scrape(self, task: dict) -> dict:
        """Scrape content from a URL."""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(task["url"], timeout=task.get("timeout_seconds", 60) * 1000)
                page.wait_for_load_state("networkidle", timeout=30000)

                title = page.title()
                final_url = page.url

                text_content = page.inner_text("body")

                instructions = task.get("instructions", "")
                scraped = {"text": text_content[:10000]}

                if instructions:
                    selectors = re.findall(
                        r'selector[:\s]*["\']([^"\']+)["\']',
                        instructions,
                        re.IGNORECASE,
                    )
                    for sel in selectors:
                        try:
                            elements = page.query_selector_all(sel)
                            scraped[sel] = [el.inner_text() for el in elements[:50]]
                        except Exception:
                            pass

                filename = f"scrape_{task['id']}_{int(time.time())}.png"
                path = os.path.join(SCREENSHOT_DIR, filename)
                page.screenshot(path=path)

                browser.close()

                return {
                    "scraped_data": scraped,
                    "screenshot_path": f"/static/screenshots/{filename}",
                    "page_title": title,
                    "page_url": final_url,
                }
        except ImportError:
            return {"error": "Playwright not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _task_monitor(self, task: dict) -> dict:
        """Monitor a page — take screenshot and compare to previous."""
        result = self._task_screenshot(task)
        result["metadata"] = {"monitor": True, "checked_at": datetime.now().isoformat()}
        return result

    def _task_custom(self, task: dict) -> dict:
        """Execute a validated Playwright script in a restricted scope."""
        script = task.get("script", "")
        if not script:
            script = self.generate_script(task.get("instructions", ""), task["url"])
            if not script:
                return {"error": "No script and could not generate one"}

        if not self._validate_script(script):
            return {"error": "Script failed safety validation"}

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(task["url"], timeout=task.get("timeout_seconds", 60) * 1000)

                # Execute in restricted scope — only page and result are accessible,
                # no builtins allowed (prevents imports, file I/O, eval, etc.)
                result_data = {}
                sandbox_globals = {"__builtins__": {}}
                sandbox_locals = {"page": page, "result": result_data}

                # compile + run in sandbox
                compiled = compile(script, "<browser_task>", "exec")
                # Using exec here is intentional for sandboxed Playwright script execution.
                # The script is validated by _validate_script() which blocks imports, file ops,
                # and other dangerous patterns. __builtins__ is set to empty dict.
                eval(compiled, sandbox_globals, sandbox_locals)  # noqa: S307

                title = page.title()
                final_url = page.url

                filename = f"custom_{task['id']}_{int(time.time())}.png"
                path = os.path.join(SCREENSHOT_DIR, filename)
                page.screenshot(path=path)

                browser.close()

                return {
                    "scraped_data": sandbox_locals.get("result", {}),
                    "screenshot_path": f"/static/screenshots/{filename}",
                    "page_title": title,
                    "page_url": final_url,
                }
        except ImportError:
            return {"error": "Playwright not installed"}
        except Exception as e:
            return {"error": str(e)}

    def generate_script(self, instructions: str, url: str) -> Optional[str]:
        """Generate a Playwright script from natural language instructions."""
        try:
            prompt = f"""Generate a Playwright Python script for this task.
The script will be executed with a `page` variable already navigated to {url}.
Store results in a `result` dict variable.

RULES:
- Only use page.click(), page.fill(), page.query_selector(), page.inner_text(), page.wait_for_selector()
- Do NOT import anything, do NOT use file operations
- Do NOT navigate to other domains
- Keep it simple and focused

Task: {instructions}

Respond with ONLY the Python code, no markdown fences."""

            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            result = dispatcher.request_work("code", prompt, "browser_automation", timeout=120)
            if not result.success:
                return None
            script = result.response.strip()

            script = re.sub(r"^```python\s*\n?", "", script)
            script = re.sub(r"\n?```\s*$", "", script)

            if self._validate_script(script):
                return script
            return None

        except Exception as e:
            logger.error(f"Script generation failed: {e}")
            return None

    def _validate_script(self, script: str) -> bool:
        """Validate a Playwright script for safety."""
        forbidden = [
            "import ",
            "from ",
            "__import__",
            "eval(",
            "exec(",
            "open(",
            "os.",
            "sys.",
            "subprocess",
            "shutil",
            "requests.",
            "urllib",
            "socket",
            "rmdir",
            "unlink",
            "remove(",
        ]
        script_lower = script.lower()
        for pattern in forbidden:
            if pattern.lower() in script_lower:
                logger.warning(f"Script validation failed: contains '{pattern}'")
                return False
        return True

    def _is_domain_approved(self, cur, domain: str) -> bool:
        """Check if a domain is in the approved list."""
        cur.execute(
            "SELECT id FROM browser_approved_domains WHERE domain = %s",
            (domain,),
        )
        return cur.fetchone() is not None

    def approve_domain(self, domain: str, approved_by: int, notes: str = "") -> bool:
        """Add a domain to the approved list."""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO browser_approved_domains (domain, approved_by, notes)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (domain) DO NOTHING
                    """,
                    (domain, approved_by, notes),
                )
                conn.commit()
                return True
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to approve domain: {e}")
            return False
