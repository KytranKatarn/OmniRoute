"""Skill runner — discovers skill files and executes them with Playwright."""
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

_LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "twitter": "https://x.com/login",
    # facebook requires manual session setup — no automated login
}


def _discover_skills() -> dict:
    """Return dict of skill_name → {module, platforms} for all skills/*.py."""
    skills = {}
    for path in Path(SKILLS_DIR).glob("*.py"):
        if path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            name = getattr(mod, "SKILL_NAME", path.stem)
            platforms = getattr(mod, "PLATFORMS", [])
            skills[name] = {"module": mod, "platforms": platforms}
        except Exception as exc:
            logger.warning("Failed to load skill %s: %s", path.name, exc)
    return skills


def run(agent_id: int, skill_name: str, params: dict) -> dict:
    """Execute a skill for an agent. Returns result dict. (Legacy — use execute())"""
    return execute(agent_id, skill_name, params)


def list_skills() -> list[dict]:
    """Return [{name, platforms}] for all discovered skills."""
    skills = _discover_skills()
    return [{"name": name, "platforms": info["platforms"]} for name, info in skills.items()]


def execute(agent_id: int, skill_name: str, params: dict) -> dict:
    """Load session, launch Playwright, run the skill, save updated session."""
    import session_manager

    skills = _discover_skills()
    if skill_name not in skills:
        raise ValueError(f"Unknown skill: {skill_name}")

    skill = skills[skill_name]
    platform = skill["platforms"][0] if skill["platforms"] else ""
    storage_state = session_manager.load_session(agent_id, platform) if platform else None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ctx_kwargs = {"storage_state": storage_state} if storage_state else {}
            context = browser.new_context(**ctx_kwargs)
            try:
                page = context.new_page()
                result = skill["module"].execute(page, params)
                updated = context.storage_state()
                if platform:
                    session_manager.save_session(agent_id, platform, updated)
                return result
            except Exception as exc:
                logger.error(
                    "Skill %s failed for agent %s: %s", skill_name, agent_id, type(exc).__name__
                )
                if platform:
                    session_manager.mark_error(agent_id, platform, str(exc))
                raise
            finally:
                context.close()
        finally:
            browser.close()


def login(agent_id: int, platform: str) -> dict:
    """Load credentials, navigate to login URL, run platform login, save session."""
    import session_manager

    creds = session_manager.get_credentials(agent_id, platform)
    if not creds:
        raise ValueError(f"No credentials found for agent {agent_id} on {platform}")

    login_url = _LOGIN_URLS.get(platform)
    if not login_url:
        raise ValueError(f"Unsupported platform for login: {platform}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context()
            try:
                page = context.new_page()
                page.goto(login_url)
                result = _do_platform_login(page, platform, creds)
                if result.get("success"):
                    session_manager.save_session(agent_id, platform, context.storage_state())
                return result
            except Exception as exc:
                logger.error(
                    "Login failed for agent %s on %s: %s", agent_id, platform, type(exc).__name__
                )
                session_manager.mark_error(agent_id, platform, str(exc))
                raise
            finally:
                context.close()
        finally:
            browser.close()


def _do_platform_login(page, platform: str, creds: dict) -> dict:
    """Platform-specific login steps. Returns {success, url}."""
    if platform == "linkedin":
        page.fill("#username", creds["username"])
        page.fill("#password", creds["password"])
        page.click('[data-litms-control-urn="login-submit"]')
        try:
            page.wait_for_url("**/feed**", timeout=10000)
            return {"success": True}
        except Exception:
            if "feed" in page.url or "mynetwork" in page.url:
                return {"success": True}
            return {"success": False, "error": "Login failed or 2FA required -- complete manually"}

    if platform in ("twitter", "x"):
        page.fill('input[autocomplete="username"]', creds["username"])
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)  # brief wait for password field
        page.fill('input[type="password"]', creds["password"])
        page.keyboard.press("Enter")
        try:
            page.wait_for_url("**/home**", timeout=10000)
            return {"success": True}
        except Exception:
            if "home" in page.url:
                return {"success": True}
            return {"success": False, "error": "Login failed or 2FA required -- complete manually"}

    raise ValueError(f"No login implementation for platform: {platform}")
