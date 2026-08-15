"""Session manager — encrypted Playwright storageState storage."""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from cryptography.fernet import InvalidToken

logger = logging.getLogger(__name__)

_fernet_cache: dict = {}


def _get_fernet():
    if "f" not in _fernet_cache:
        from cryptography.fernet import Fernet
        key = os.getenv("BROWSER_ENCRYPTION_KEY", "")
        if not key:
            raise ValueError("BROWSER_ENCRYPTION_KEY env var not set")
        _fernet_cache["f"] = Fernet(key.encode())
    return _fernet_cache["f"]


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def _get_conn():
    import psycopg2
    import psycopg2.extras
    dsn = os.getenv("DATABASE_URL") or psycopg2.extensions.make_dsn(
        host=os.getenv("DB_HOST", "archie_database"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    conn = psycopg2.connect(dsn)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def load_session(agent_id: int, platform: str) -> Optional[dict]:
    """Load Playwright storage_state for (agent_id, platform).

    Layer A Phase 1: fetch from platform HTTP API instead of local disk.
    Returns None on any failure — caller (skill_runner) handles by passing
    None to Playwright's new_context (= unauthenticated session). The
    skill will fail naturally; reactive layer (Phase 3) will mark stale.
    """
    import requests

    platform_url = os.getenv("ARCHIE_PLATFORM_URL", "http://archie_platform:3000")
    internal_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_key:
        logger.warning("INTERNAL_API_KEY not set; cannot load session via HTTP")
        return None

    # /tools/department-hq/* has invisible auth middleware that 302-redirects
    # all unauth requests to /dashboard. Use the app-level internal route
    # (Bearer auth, matches /api/internal/delegation/* pattern) instead.
    url = f"{platform_url}/api/internal/sessions/{agent_id}/{platform}/state"
    try:
        resp = requests.get(
            url, headers={"Authorization": f"Bearer {internal_key}"}, timeout=5
        )
    except Exception as exc:
        logger.warning("session HTTP fetch failed: %s", exc)
        return None

    if resp.status_code == 404:
        return None  # no active session — skill will fail at next selector
    if resp.status_code != 200:
        logger.warning("session HTTP fetch %s: %s", resp.status_code, resp.text[:120])
        return None

    return resp.json().get("state")


def save_session(agent_id: int, platform: str, storage_state: dict) -> None:
    """Encrypt and upsert storageState."""
    encrypted = _encrypt(json.dumps(storage_state))
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO agent_browser_sessions
                (agent_id, platform, session_data_encrypted, status, last_used_at,
                 session_expires_at, updated_at)
            VALUES (%s, %s, %s, 'active', NOW(), %s, NOW())
            ON CONFLICT (agent_id, platform) DO UPDATE SET
                session_data_encrypted = EXCLUDED.session_data_encrypted,
                status = 'active',
                last_used_at = NOW(),
                session_expires_at = EXCLUDED.session_expires_at,
                updated_at = NOW()
            """,
            (agent_id, platform, encrypted, expires_at),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.error("save_session(%s, %s) failed: %s", agent_id, platform, type(exc).__name__)
        raise
    finally:
        if conn:
            conn.close()


def save_credentials(agent_id: int, platform: str, username: str, password: str) -> None:
    """Encrypt and store login credentials."""
    enc_pass = _encrypt(password)
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO agent_browser_sessions (agent_id, platform, username, password_encrypted, status)
            VALUES (%s, %s, %s, %s, 'missing')
            ON CONFLICT (agent_id, platform) DO UPDATE SET
                username = EXCLUDED.username,
                password_encrypted = EXCLUDED.password_encrypted,
                updated_at = NOW()
            """,
            (agent_id, platform, username, enc_pass),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.error("save_credentials(%s, %s) failed: %s", agent_id, platform, type(exc).__name__)
        raise
    finally:
        if conn:
            conn.close()


def get_credentials(agent_id: int, platform: str) -> Optional[dict]:
    """Return decrypted {username, password} or None if not found."""
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT username, password_encrypted FROM agent_browser_sessions "
            "WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )
        row = cur.fetchone()
        cur.close()
        if not row or not row["username"] or not row["password_encrypted"]:
            return None
        return {
            "username": row["username"],
            "password": _decrypt(row["password_encrypted"]),
        }
    except InvalidToken:
        logger.error("get_credentials(%s, %s): decryption failed -- key mismatch or corrupt data", agent_id, platform)
        return None
    except Exception as exc:
        logger.warning("get_credentials(%s, %s) failed: %s", agent_id, platform, type(exc).__name__)
        return None
    finally:
        if conn:
            conn.close()


def get_session_status(agent_id: int, platform: str) -> dict:
    """Return status dict for an agent/platform session."""
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT status, last_used_at, session_expires_at FROM agent_browser_sessions "
            "WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return {"status": "missing", "last_used": None}
        return {
            "status": row["status"],
            "last_used": row["last_used_at"].isoformat() if row["last_used_at"] else None,
            "expires_at": row["session_expires_at"].isoformat() if row["session_expires_at"] else None,
        }
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
    finally:
        if conn:
            conn.close()


def refresh_session(agent_id: int, platform: str) -> dict:
    """Signal that a session refresh is needed. Returns success/failure dict."""
    creds = get_credentials(agent_id, platform)
    if not creds:
        return {
            "success": False,
            "error": f"No credentials found for agent {agent_id} on {platform}",
        }
    return {
        "success": True,
        "message": "refresh_pending",
        "agent_id": agent_id,
        "platform": platform,
    }


def mark_error(agent_id: int, platform: str, error: str) -> None:
    """Set status='error' on the session row."""
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE agent_browser_sessions
            SET status = 'error', updated_at = NOW()
            WHERE agent_id = %s AND platform = %s
            """,
            (agent_id, platform),
        )
        conn.commit()
        cur.close()
        logger.warning("mark_error(%s, %s): %s", agent_id, platform, str(error)[:200])
    except Exception as exc:
        logger.error("mark_error DB write failed: %s", type(exc).__name__)
    finally:
        if conn:
            conn.close()


PROFILES_DIR = os.getenv("BROWSER_PROFILES_DIR", "/profiles")

_LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "twitter": "https://x.com/login",
    "facebook": "https://www.facebook.com/login",
}

# A URL containing any of these means we are NOT authenticated. Same list the
# skill_runner logged-out probe uses — keep them in step (#5627).
_LOGGED_OUT_MARKERS = (
    "linkedin.com/login",
    "linkedin.com/authwall",
    "linkedin.com/checkpoint",
    "linkedin.com/signup",
    "linkedin.com/uas/",
)
_CHALLENGE_MARKERS = ("checkpoint", "challenge", "two_factor", "verification")


def _profile_dir_for(agent_id: int, platform: str) -> str:
    """The SAME dir skill_runner opens for posting (`/profiles/<agent>-<platform>`)."""
    return os.path.join(PROFILES_DIR, f"{agent_id}-{platform}")


def _export_state_to_hub_vault(agent_id: int, platform: str, storage_state: dict) -> bool:
    """Push storage_state to the PLATFORM's `browser_sessions` (mirrors login_browser).

    ⚠️ THIS IS WHAT ACTUALLY UNPAUSES POSTING. There are two session tables and this
    container only writes one of them:
      • `agent_browser_sessions`  — browser-container local (save_session/mark_error)
      • `browser_sessions`        — PLATFORM side; `signal_calendar_service.
        _linkedin_profile_healthy()` gates the daily release on ITS `status`, and
        `record_probe` is what writes it.
    So a re-login that only calls save_session leaves the calendar gate reading
    'stale' forever and the account stays paused despite a healthy profile. Same
    class of split-brain as the #5627 sensor bug — fix the signal the CONSUMER reads.

    Best-effort: the on-disk profile is the primary artifact; never raise.
    """
    # See challenge_code: archie_browser gets ARCHIE_PLATFORM_URL, the login sidecar
    # gets PLATFORM_INTERNAL_URL. Accept either or this silently never clears the gate.
    hub = (os.getenv("PLATFORM_INTERNAL_URL") or os.getenv("ARCHIE_PLATFORM_URL") or "").rstrip("/")
    token = os.getenv("INTERNAL_API_KEY", "")
    if not (hub and token):
        logger.warning("[Session] no platform URL / INTERNAL_API_KEY — "
                       "calendar gate will NOT be cleared for %s/%s", agent_id, platform)
        return False
    try:
        import requests

        r = requests.post(
            f"{hub}/api/internal/sessions/{agent_id}/{platform}/state",
            json={"state": storage_state},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        ok = 200 <= r.status_code < 300
        logger.info("[Session] hub vault export %s/%s: HTTP %s", agent_id, platform, r.status_code)
        return ok
    except Exception as exc:
        logger.warning("[Session] hub vault export failed: %s", type(exc).__name__)
        return False


def _is_logged_out(url: str) -> bool:
    return any(m in (url or "") for m in _LOGGED_OUT_MARKERS)


def _submit_challenge_code(page, code: str) -> None:
    """Type a verification code into whichever field LinkedIn rendered."""
    for sel in ("input[name='pin']", "#input__email_verification_pin",
                "input[autocomplete='one-time-code']", "input[name='verification_code']"):
        try:
            if page.locator(sel).count():
                page.fill(sel, code)
                break
        except Exception:
            continue
    for sel in ("#email-pin-submit-button", "button[type='submit']"):
        try:
            if page.locator(sel).count():
                page.click(sel)
                break
        except Exception:
            continue
    page.wait_for_load_state("networkidle", timeout=20000)


def setup_session(
    agent_id: int,
    platform: str,
    username: str,
    password: str,
    *,
    verification_code: str = None,
    auto_code: bool = True,
) -> dict:
    """Re-login INSIDE the persistent posting profile, and prove it worked.

    ⚠️ #5627 — WHAT THIS USED TO DO AND WHY IT COULD NEVER WORK. The old version
    logged in through an EPHEMERAL `browser.new_context()` and saved the resulting
    storage_state to `browser_sessions`. But posting does not read that: skill_runner
    opens `launch_persistent_context('/profiles/<agent>-<platform>')`. So a
    "successful" automated re-login refreshed the READ path and left the POSTING
    profile logged out — the caller then logged "[Session] re-login complete" and
    posts kept failing into a dead profile. That is KB #274241 expressed as code, and
    the same false-success shape as the #1831 guard it was supposed to back up.

    Logging in inside the EXISTING profile is also what makes an automated login
    viable at all: LinkedIn sees the device fingerprint and residual cookies it has
    already trusted, instead of a brand-new context that all but guarantees a
    step-up. The fingerprint now comes from `browser_fingerprint` so it cannot drift
    from the noVNC login that established that trust.

    Returns an HONEST status — 'active' only after a positive re-check of the feed:
      active     — verified authenticated in the posting profile
      needs_2fa  — a challenge we could not clear; hand off to noVNC
      failed     — credentials rejected or the profile is still logged out
    """
    from playwright.sync_api import sync_playwright

    import browser_fingerprint

    login_url = _LOGIN_URLS.get(platform)
    if not login_url:
        raise ValueError(f"Unknown platform: {platform}")

    save_credentials(agent_id, platform, username, password)

    profile_dir = _profile_dir_for(agent_id, platform)
    os.makedirs(profile_dir, exist_ok=True)
    result: dict = {"status": "failed", "platform": platform, "agent_id": agent_id}

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            profile_dir,
            **browser_fingerprint.persistent_context_kwargs(headless=True),
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

            # Idempotent: if the profile is in fact still authenticated, LinkedIn
            # bounces /login straight to the feed. Do not retype a password and risk
            # a needless challenge.
            if not _is_logged_out(page.url):
                logger.info("[Session] %s/%s already authenticated — no login needed", agent_id, platform)
            else:
                # Stamp BEFORE submitting: any verification mail older than this is
                # from a previous attempt and must not be accepted (see challenge_code).
                import time as _time

                attempt_started = _time.time()

                if platform == "linkedin":
                    page.fill("#username", username)
                    page.fill("#password", password)
                    page.click('[data-litms-control-urn="login-submit"]')
                    page.wait_for_load_state("networkidle", timeout=30000)
                elif platform in ("twitter", "x"):
                    page.fill('[autocomplete="username"]', username)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1500)
                    page.fill('[autocomplete="current-password"]', password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle", timeout=30000)

                # --- Slice 2: clear an email challenge on our own ---
                if any(m in page.url for m in _CHALLENGE_MARKERS):
                    code = verification_code
                    if not code and auto_code and platform == "linkedin":
                        try:
                            import challenge_code

                            code = challenge_code.fetch_verification_code(
                                username, not_before=attempt_started
                            )
                        except Exception as exc:
                            logger.warning("[Session] auto-code lookup failed: %s", type(exc).__name__)
                    if code:
                        _submit_challenge_code(page, code)

                # Still challenged (phone / CAPTCHA / bad code) -> honest handoff.
                if any(m in page.url for m in _CHALLENGE_MARKERS):
                    shot = f"/tmp/2fa_{agent_id}_{platform}.png"
                    try:
                        page.screenshot(path=shot)
                    except Exception:
                        shot = None
                    mark_error(agent_id, platform, "challenge requires human (noVNC)")
                    result = {"status": "needs_2fa", "screenshot_path": shot,
                              "platform": platform, "agent_id": agent_id}
                    return result

            # --- VERIFY BY OUTPUT, not by absence of an exception (ADR #983) ---
            # A submitted form that silently failed still leaves a loaded page. The
            # only thing that counts is the feed rendering while authenticated.
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
            if _is_logged_out(page.url):
                mark_error(agent_id, platform, "re-login did not authenticate the profile")
                logger.error("[Session] %s/%s re-login FAILED — still logged out at %s",
                             agent_id, platform, page.url)
                result = {"status": "failed", "reason": "still_logged_out",
                          "platform": platform, "agent_id": agent_id}
                return result

            # Seed BOTH session stores so every consumer agrees with disk:
            #   save_session            -> agent_browser_sessions (this container)
            #   _export_state_to_hub_vault -> browser_sessions (what the calendar gate reads)
            gate_cleared = False
            try:
                state = context.storage_state()
                save_session(agent_id, platform, state)
                gate_cleared = _export_state_to_hub_vault(agent_id, platform, state)
            except Exception as exc:
                logger.warning("[Session] storage_state export failed (non-fatal): %s", type(exc).__name__)

            logger.info("[Session] %s/%s re-login VERIFIED in posting profile (calendar gate cleared=%s)",
                        agent_id, platform, gate_cleared)
            result = {"status": "active", "platform": platform, "agent_id": agent_id,
                      "profile_dir": profile_dir, "gate_cleared": gate_cleared}
            return result
        finally:
            # Flushes cookies/localStorage/fingerprint to disk — without this the
            # profile on disk keeps the OLD (logged-out) state and nothing changed.
            try:
                context.close()
            except Exception:
                pass
