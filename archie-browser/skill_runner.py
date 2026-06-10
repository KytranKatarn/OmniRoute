"""Skill runner — discovers skill files and executes them with Playwright."""
import importlib.util
import logging
import os
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

# Persistent trusted-session profiles (#3953). A profile dir at
# {PROFILES_DIR}/{agent_id}-{platform} that was established by a ONE-TIME
# human login (archie_browser_login sidecar / S.I.G.N.A.L. session panel)
# carries the full device fingerprint LinkedIn trusts — not just cookies.
# When present, skills run inside launch_persistent_context on that dir
# instead of an ephemeral storage_state context. Chromium profiles are
# single-process: access is serialized per profile via _profile_locks.
PROFILES_DIR = os.getenv("BROWSER_PROFILES_DIR", "/profiles")

_profile_locks: dict = {}
_profile_locks_guard = threading.Lock()


def _profile_dir(agent_id: int, platform: str):
    """Return the persistent profile dir for (agent, platform) if ESTABLISHED."""
    if not platform:
        return None
    d = os.path.join(PROFILES_DIR, f"{agent_id}-{platform}")
    try:
        if os.path.isdir(d) and os.listdir(d):
            return d
    except OSError:
        pass
    return None


def _lock_for(profile_dir: str) -> threading.Lock:
    with _profile_locks_guard:
        if profile_dir not in _profile_locks:
            _profile_locks[profile_dir] = threading.Lock()
        return _profile_locks[profile_dir]


class _ProfileUnavailable(Exception):
    """Persistent profile could not be LAUNCHED (lock held / corrupt dir).

    Distinct from skill-phase failures so the caller can safely fall back to
    the storage_state path without risking a double-execution of a skill
    that already ran.
    """

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

    # Persistent trusted profile path (#3953) — preferred when established.
    profile_dir = _profile_dir(agent_id, platform)
    if profile_dir:
        try:
            return _execute_persistent(agent_id, skill, skill_name, platform, profile_dir, params)
        except _ProfileUnavailable as exc:
            # Launch-phase failure ONLY (e.g. ProcessSingleton lock while the
            # owner is mid-login in the sidecar) → fall back to the legacy
            # storage_state path. Skill-phase errors propagate — the skill may
            # already have acted (a re-run could double-post).
            logger.warning(
                "[Profile] persistent context unavailable for %s/%s (%s) — "
                "falling back to storage_state",
                agent_id, platform, exc,
            )

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

                # Session expiry detection — if LinkedIn redirected to login, refresh
                current_url = page.url
                _logged_out = any(
                    x in current_url
                    for x in ("linkedin.com/login", "linkedin.com/authwall",
                              "linkedin.com/checkpoint", "linkedin.com/signup",
                              "linkedin.com/uas/")
                )
                if _logged_out and platform:
                    logger.warning(
                        "[Session] Agent %s session expired on %s — attempting re-login",
                        agent_id, platform,
                    )
                    creds = session_manager.get_credentials(agent_id, platform)
                    if creds:
                        session_manager.setup_session(
                            agent_id, platform,
                            creds["username"], creds["password"]
                        )
                        logger.info("[Session] Agent %s re-login complete", agent_id)
                    else:
                        logger.error("[Session] No credentials for agent %s/%s", agent_id, platform)

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


def _execute_persistent(
    agent_id: int, skill: dict, skill_name: str, platform: str, profile_dir: str, params: dict
) -> dict:
    """Run a skill inside the persistent trusted profile (#3953).

    The profile self-persists (cookies + localStorage + device fingerprint on
    disk); we additionally export storage_state to the DB so READ-path
    consumers (authenticated_fetch / S.C.O.U.T. fabric) stay in sync. On a
    logged-out redirect we do NOT attempt a headless re-login — that would
    taint the trusted profile; re-auth goes through the S.I.G.N.A.L. session
    panel (human, headed).
    """
    import session_manager

    with _lock_for(profile_dir):
        with sync_playwright() as p:
            try:
                # Match the login browser's anti-detection fingerprint
                # (login_browser.py) so the replayed session stays trusted —
                # a mismatch re-triggers LinkedIn's step-up. (#3953)
                context = p.chromium.launch_persistent_context(
                    profile_dir,
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    ignore_default_args=["--enable-automation"],
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
            except Exception as exc:
                raise _ProfileUnavailable(f"{type(exc).__name__}: {exc}") from exc
            try:
                page = context.new_page()
                result = skill["module"].execute(page, params)

                current_url = page.url
                _logged_out = any(
                    x in current_url
                    for x in ("linkedin.com/login", "linkedin.com/authwall",
                              "linkedin.com/checkpoint", "linkedin.com/signup",
                              "linkedin.com/uas/")
                )
                if _logged_out:
                    logger.error(
                        "[Profile] Agent %s trusted profile logged out on %s — "
                        "re-auth required via S.I.G.N.A.L. session panel",
                        agent_id, platform,
                    )
                    session_manager.mark_error(
                        agent_id, platform, "trusted profile logged out — human re-auth required"
                    )
                else:
                    session_manager.save_session(agent_id, platform, context.storage_state())
                return result
            except Exception as exc:
                logger.error(
                    "Skill %s (persistent) failed for agent %s: %s",
                    skill_name, agent_id, type(exc).__name__,
                )
                session_manager.mark_error(agent_id, platform, str(exc))
                raise
            finally:
                context.close()


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
