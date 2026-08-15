"""Skill runner — discovers skill files and executes them with Playwright."""
import importlib.util
import logging
import os
import threading
import time
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


# #3948 — bound the per-profile lock + self-recover a wedged profile. A crashed
# chrome whose Playwright thread hangs on the dead CDP connection holds _lock_for
# FOREVER (context.close() never returns), so every later skill on that profile
# blocks until the caller's 120s timeout. We acquire the lock WITH a timeout and,
# if a holder is stuck, force-kill its chrome so the held lock releases and the
# profile self-recovers on the next call. (Tunable; default 90s < the 120s client.)
_LOCK_ACQUIRE_TIMEOUT_S = int(os.getenv("BROWSER_PROFILE_LOCK_TIMEOUT_S", "90"))

# Default per-page navigation + action timeout. Before this, skills set NO timeout, so
# an un-timed page.goto rode Playwright's 30s default and a slow/wedged feed could stack
# multiple gotos past the platform's 180s client ceiling (linkedin_post does two gotos →
# ~235s worst case). A hard cap makes every navigation fail fast + observably instead of
# hanging silently. (#4372)
_NAV_TIMEOUT_MS = int(os.getenv("BROWSER_NAV_TIMEOUT_MS", "20000"))

# Skills that only READ may safely run on the storage_state fallback context when the
# persistent profile is momentarily locked. Everything else MUTATES (post/like/comment/
# connect/edit) — running a mutating skill on a possibly-unauthed fallback risks a
# logged-out 120s composer hang or, worse, a DOUBLE-POST. So mutating skills FAIL FAST
# when the trusted profile is unavailable and the scheduler reschedules them. (#4372)
_READ_ONLY_SKILLS = {
    "linkedin_feed", "linkedin_notifications", "linkedin_search", "linkedin_inbox",
    "linkedin_recent_activity", "linkedin_analytics", "linkedin_profile_view",
    "linkedin_post_comments", "linkedin_company_inbox", "session_probe",
}


def _is_mutating(skill_name: str, module) -> bool:
    """True unless the skill is on the read-only allowlist (conservative default: an
    unknown/new skill is treated as mutating). An explicit module-level MUTATING flag
    on the skill overrides the allowlist."""
    flag = getattr(module, "MUTATING", None)
    if flag is not None:
        return bool(flag)
    return skill_name not in _READ_ONLY_SKILLS


# S7-P6.6 — sidecar-side ROLE allowlist. A supporting_engagement account may like / share /
# comment on others' posts but must PHYSICALLY be unable to AUTHOR (post / company-post /
# profile-edit). Enforced here (not just platform-side) so a misconfigured supporting agent
# cannot author even if a caller targets it directly. The restriction is a POSITIVE opt-in:
# only an account whose registry role is supporting_engagement (and not also a major/company)
# is restricted — a major/company/unknown agent, or any lookup error, is unrestricted, so
# today's 4 accounts (all major_author/company_page) are a strict no-op.
_ROLE_ALLOWLIST_ENABLED = os.getenv("BROWSER_ROLE_ALLOWLIST_ENABLED", "true").strip().lower() not in (
    "false", "0", "off", "no",
)
_SUPPORTING_ENGAGEMENT_SKILLS = {
    "linkedin_comment", "linkedin_first_comment", "linkedin_comment_reply",
    "linkedin_like", "linkedin_share",
}
_role_cache: dict = {}  # agent_id -> (role, ts)
_role_cache_lock = threading.Lock()
_ROLE_CACHE_TTL_S = int(os.getenv("BROWSER_ROLE_CACHE_TTL_S", "300"))


def _role_for(agent_id) -> str:
    """Cached: 'restricted' iff the agent's ONLY registry role is supporting_engagement;
    'unrestricted' otherwise (a major/company account, an unknown agent with no row, or ANY
    lookup error). The restriction never blocks a major — it is a positive opt-in for
    explicitly-supporting agents."""
    now = time.time()
    with _role_cache_lock:
        hit = _role_cache.get(agent_id)
        if hit and (now - hit[1]) < _ROLE_CACHE_TTL_S:
            return hit[0]
    role = "unrestricted"
    try:
        import psycopg2

        conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT bool_or(role IN ('major_author','company_page')) AS has_author, "
                "       bool_or(role = 'supporting_engagement') AS has_support "
                "FROM agent_platform_accounts WHERE browser_agent_id = %s",
                (agent_id,),
            )
            r = cur.fetchone()
            cur.close()
            if r and not r[0] and r[1]:  # supporting present AND no major/company row
                role = "restricted"
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[Role] role lookup failed for agent %s (allowing): %s", agent_id, exc)
        role = "unrestricted"
    with _role_cache_lock:
        _role_cache[agent_id] = (role, now)
    return role


def _allowed_for_role(skill_name: str, module, role: str) -> bool:
    """A 'restricted' (supporting_engagement) account may run read-only skills + the
    engagement (non-authoring) mutating skills only. Everyone else is unrestricted."""
    if role != "restricted":
        return True
    if not _is_mutating(skill_name, module):
        return True
    return skill_name in _SUPPORTING_ENGAGEMENT_SKILLS


def _set_page_timeouts(page) -> None:
    """Apply the default navigation + action timeout to a freshly created page so no
    un-timed goto/locator can hang to the 180s client ceiling. Best-effort."""
    try:
        page.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
        page.set_default_timeout(_NAV_TIMEOUT_MS)
    except Exception:
        pass


def _kill_chrome_for_profile(profile_dir: str) -> int:
    """SIGKILL any chrome bound to profile_dir (matched via /proc cmdline, i.e. its
    --user-data-dir). Pure-Python so the image needs no pkill. Access is serialized
    per profile, so at most the single stuck chrome matches."""
    import signal as _signal

    # Safety (#3948 review): only ever act on an established profile path UNDER
    # PROFILES_DIR. A blank/short/too-broad value would substring-match — and SIGKILL
    # — unrelated chrome procs. Refuse anything that isn't a real /profiles/<name>.
    if not profile_dir or not profile_dir.startswith(PROFILES_DIR + "/") or len(profile_dir) <= len(PROFILES_DIR) + 1:
        logger.error("[Profile] refusing force-kill for suspicious profile_dir %r", profile_dir)
        return 0

    killed = 0
    try:
        pids = os.listdir("/proc")
    except OSError:
        return 0
    for ent in pids:
        if not ent.isdigit():
            continue
        try:
            with open(f"/proc/{ent}/cmdline", "rb") as fh:
                cmd = fh.read().decode("utf-8", "ignore")
            if profile_dir in cmd and "chrom" in cmd.lower():
                os.kill(int(ent), _signal.SIGKILL)
                killed += 1
        except (OSError, ValueError, ProcessLookupError):
            continue
    if killed:
        logger.warning("[Profile] force-killed %d stuck chrome proc(s) for %s", killed, profile_dir)
    return killed


def kill_agent_chrome(agent_id) -> int:
    """Watchdog unwedge: SIGKILL any chrome bound to ANY profile dir of this agent
    (PROFILES_DIR/<agent_id>-<platform>, matched via /proc cmdline --user-data-dir).
    Called by the sidecar per-task watchdog to free a wedged per-profile lock when a
    task exceeds its deadline. Strict guard — the trailing '-' on the prefix prevents
    agent 34 matching 342-... and a blank/zero id matching everything."""
    import signal as _signal

    try:
        prefix = os.path.join(PROFILES_DIR, f"{int(agent_id)}-")
    except (TypeError, ValueError):
        return 0
    if len(prefix) <= len(PROFILES_DIR) + 1:
        return 0
    killed = 0
    try:
        pids = os.listdir("/proc")
    except OSError:
        return 0
    for ent in pids:
        if not ent.isdigit():
            continue
        try:
            with open(f"/proc/{ent}/cmdline", "rb") as fh:
                cmd = fh.read().decode("utf-8", "ignore")
            if prefix in cmd and "chrom" in cmd.lower():
                os.kill(int(ent), _signal.SIGKILL)
                killed += 1
        except (OSError, ValueError, ProcessLookupError):
            continue
    if killed:
        logger.warning("[Watchdog] force-killed %d chrome proc(s) for agent %s", killed, agent_id)
    return killed


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
        # Skip private/helper modules (e.g. _linkedin_common.py) and __init__.py —
        # they define shared code, not runnable skills (#2599).
        if path.name.startswith("_"):
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
    # #4006: platform-agnostic skills (PLATFORMS=[], e.g. session_probe) are
    # bound to a session/profile at call time via params["_platform"] —
    # popped so it never reaches the skill's own params.
    platform = str(params.pop("_platform", "") or "").strip().lower() or (
        skill["platforms"][0] if skill["platforms"] else ""
    )

    # S7-P6.6: role allowlist — a supporting_engagement account physically cannot author.
    # No-op for today's major/company accounts; pure safety for future supporting agents.
    if _ROLE_ALLOWLIST_ENABLED:
        _role = _role_for(agent_id)
        if not _allowed_for_role(skill_name, skill["module"], _role):
            logger.error(
                "[Role] agent %s blocked from author skill %s (role=%s, supporting_engagement)",
                agent_id, skill_name, _role,
            )
            return {
                "success": False,
                "error": f"skill '{skill_name}' not permitted for a supporting_engagement account",
                "_role_blocked": True,
            }

    # Persistent trusted profile path (#3953) — preferred when established.
    profile_dir = _profile_dir(agent_id, platform)
    if profile_dir:
        try:
            _persistent_result = _execute_persistent(
                agent_id, skill, skill_name, platform, profile_dir, params
            )
        except _ProfileUnavailable as exc:
            # Launch-phase failure ONLY (e.g. ProcessSingleton lock while the owner is
            # mid-login, or a wedged chrome the watchdog just killed). A MUTATING skill
            # must NOT run on the storage_state fallback — that context may be unauthed
            # (the trusted on-disk profile is the source of truth), which produces a
            # logged-out composer hang or, worse, a DOUBLE-POST. Fail fast so the
            # scheduler reschedules once the profile frees; only READ skills fall back.
            if _is_mutating(skill_name, skill["module"]):
                logger.error(
                    "[Profile] %s/%s MUTATING skill %s — trusted profile unavailable "
                    "(%s); failing fast, NO unauthed storage_state fallback",
                    agent_id, platform, skill_name, exc,
                )
                raise
            logger.warning(
                "[Profile] persistent context unavailable for %s/%s (%s) — "
                "read-only skill, falling back to storage_state",
                agent_id, platform, exc,
            )
        else:
            # #5627 slice 1 — the profile said it is logged out. Re-login HERE, not
            # inside _execute_persistent: that function holds both the profile lock
            # and an open context on the same dir, so an in-place login would collide
            # on chrome's ProcessSingleton. By this point the lock is released and the
            # context is closed, so the profile is ours to repair.
            #
            # We do NOT retry the skill afterwards. The skill may be MUTATING and a
            # blind retry is exactly how a double-post happens; the repair makes the
            # NEXT scheduled run succeed, which is the whole point of a drip/queue.
            if isinstance(_persistent_result, dict) and _persistent_result.get("logged_out"):
                _attempt_profile_relogin(agent_id, platform)
            return _persistent_result

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
                _set_page_timeouts(page)
                result = skill["module"].execute(page, params)

                # Session expiry detection — if LinkedIn redirected to login, refresh
                current_url = page.url
                _logged_out = any(
                    x in current_url
                    for x in ("linkedin.com/login", "linkedin.com/authwall",
                              "linkedin.com/checkpoint", "linkedin.com/signup",
                              "linkedin.com/uas/")
                )
                # Surface a positive logged-out signal to the caller so the health
                # probe (Slice 2) can distinguish real logout from a transient timeout.
                if _logged_out and isinstance(result, dict):
                    result["logged_out"] = True
                if _logged_out and platform:
                    logger.warning(
                        "[Session] Agent %s session expired on %s — attempting re-login",
                        agent_id, platform,
                    )
                    # Honour the result — see _attempt_profile_relogin. The old code
                    # here discarded it and logged "re-login complete" even when
                    # setup_session had returned needs_2fa.
                    _attempt_profile_relogin(agent_id, platform)

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


def _attempt_profile_relogin(agent_id: int, platform: str) -> dict:
    """Repair a logged-out posting profile, and report HONESTLY what happened (#5627).

    The predecessor called setup_session and then logged "re-login complete"
    unconditionally — the return value was DISCARDED, so a `needs_2fa` result was
    announced as a success. That is the same false-success shape as the #1831 guard
    this backs up, and it is why a dead profile looked healthy.

    MUST be called with the profile lock released and no open context on the dir.
    """
    import session_manager

    creds = session_manager.get_credentials(agent_id, platform)
    if not creds:
        logger.error(
            "[Session] %s/%s logged out and NO stored credentials — "
            "human re-auth required via the S.I.G.N.A.L. session panel",
            agent_id, platform,
        )
        return {"status": "no_credentials"}

    try:
        res = session_manager.setup_session(
            agent_id, platform, creds["username"], creds["password"]
        ) or {}
    except Exception as exc:
        logger.error("[Session] %s/%s auto re-login raised: %s", agent_id, platform, type(exc).__name__)
        return {"status": "failed", "reason": type(exc).__name__}

    status = res.get("status")
    if status == "active":
        logger.info("[Session] %s/%s auto re-login SUCCEEDED (gate_cleared=%s)",
                    agent_id, platform, res.get("gate_cleared"))
    elif status == "needs_2fa":
        # Not a failure of the design — a challenge only a human can clear.
        logger.error(
            "[Session] %s/%s auto re-login hit a challenge we cannot clear "
            "(phone/CAPTCHA) — noVNC handoff required. screenshot=%s",
            agent_id, platform, res.get("screenshot_path"),
        )
    else:
        logger.error("[Session] %s/%s auto re-login FAILED: %s", agent_id, platform, res)
    return res


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

    _lock = _lock_for(profile_dir)
    if not _lock.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S):
        # Stuck holder (#3948) — a crashed chrome whose thread hung on the dead CDP
        # connection. Force-kill its chrome so the held lock releases, then fail THIS
        # attempt fast → run_skill falls back to the storage_state path; the next call
        # gets the freed profile.
        logger.error(
            "[Profile] %s lock busy >%ss — stuck holder; force-killing its chrome to recover (#3948)",
            profile_dir, _LOCK_ACQUIRE_TIMEOUT_S,
        )
        _kill_chrome_for_profile(profile_dir)
        raise _ProfileUnavailable(f"profile lock busy >{_LOCK_ACQUIRE_TIMEOUT_S}s — killed stuck chrome")
    try:
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
                _set_page_timeouts(page)
                result = skill["module"].execute(page, params)

                current_url = page.url
                _logged_out = any(
                    x in current_url
                    for x in ("linkedin.com/login", "linkedin.com/authwall",
                              "linkedin.com/checkpoint", "linkedin.com/signup",
                              "linkedin.com/uas/")
                )
                # Surface a positive logged-out signal so the health probe (Slice 2)
                # can flip 'stale' ONLY on real logout, not a transient timeout.
                if _logged_out and isinstance(result, dict):
                    result["logged_out"] = True
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
    finally:
        _lock.release()


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
