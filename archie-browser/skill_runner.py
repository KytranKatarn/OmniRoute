"""Skill runner — discovers skill files and executes them with Playwright."""
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


def _discover_skills() -> dict:
    """Return dict of skill_name → module for all skills/*.py."""
    skills = {}
    for path in Path(SKILLS_DIR).glob("*.py"):
        if path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            name = getattr(mod, "SKILL_NAME", path.stem)
            skills[name] = mod
        except Exception as exc:
            logger.warning("Failed to load skill %s: %s", path.name, exc)
    return skills


def run(agent_id: int, skill_name: str, params: dict) -> dict:
    """Execute a skill for an agent. Returns result dict."""
    from playwright.sync_api import sync_playwright
    import session_manager

    skills = _discover_skills()
    if skill_name not in skills:
        raise ValueError(f"Unknown skill: {skill_name}. Available: {list(skills.keys())}")

    skill_mod = skills[skill_name]
    platforms = getattr(skill_mod, "PLATFORMS", [])
    platform = platforms[0] if platforms else "web"

    storage_state = session_manager.load_session(agent_id, platform)
    if storage_state is None:
        raise RuntimeError(
            f"No active session for agent {agent_id} on {platform}. "
            f"Run POST /session/setup first."
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()
        try:
            result = skill_mod.execute(page, params)
            session_manager.save_session(agent_id, platform, context.storage_state())
            return result
        finally:
            context.close()
            browser.close()


def list_skills() -> list:
    return list(_discover_skills().keys())
