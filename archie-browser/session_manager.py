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
    conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def load_session(agent_id: int, platform: str) -> Optional[dict]:
    """Load and decrypt storageState. Returns dict or None."""
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT session_data_encrypted, status FROM agent_browser_sessions "
            "WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )
        row = cur.fetchone()
        cur.close()
        if not row or not row["session_data_encrypted"] or row["status"] == "expired":
            return None
        return json.loads(_decrypt(row["session_data_encrypted"]))
    except InvalidToken:
        logger.error("load_session(%s, %s): decryption failed -- key mismatch or corrupt data", agent_id, platform)
        return None
    except Exception as exc:
        logger.warning("load_session(%s, %s) failed: %s", agent_id, platform, type(exc).__name__)
        return None
    finally:
        if conn:
            conn.close()


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


def setup_session(agent_id: int, platform: str, username: str, password: str) -> dict:
    """Log in to a platform and save session."""
    from playwright.sync_api import sync_playwright

    _LOGIN_URLS = {
        "linkedin": "https://www.linkedin.com/login",
        "twitter": "https://x.com/login",
        "facebook": "https://www.facebook.com/login",
    }
    login_url = _LOGIN_URLS.get(platform)
    if not login_url:
        raise ValueError(f"Unknown platform: {platform}")

    save_credentials(agent_id, platform, username, password)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)

        if platform == "linkedin":
            page.fill("#username", username)
            page.fill("#password", password)
            page.click('[data-litms-control-urn="login-submit"]')
            page.wait_for_load_state("networkidle", timeout=15000)
        elif platform in ("twitter", "x"):
            page.fill('[autocomplete="username"]', username)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            page.fill('[autocomplete="current-password"]', password)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle", timeout=15000)

        current_url = page.url
        is_2fa = any(x in current_url for x in ("checkpoint", "challenge", "two_factor", "verification"))

        if is_2fa:
            screenshot_path = f"/tmp/2fa_{agent_id}_{platform}.png"
            page.screenshot(path=screenshot_path)
            browser.close()
            return {"status": "needs_2fa", "screenshot_path": screenshot_path}

        storage_state = context.storage_state()
        save_session(agent_id, platform, storage_state)
        browser.close()

    return {"status": "active", "platform": platform, "agent_id": agent_id}
