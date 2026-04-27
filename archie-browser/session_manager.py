"""Session manager — encrypted Playwright storageState storage."""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

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
        conn.close()
        if not row or not row["session_data_encrypted"] or row["status"] == "expired":
            return None
        return json.loads(_decrypt(row["session_data_encrypted"]))
    except Exception as exc:
        logger.warning("load_session(%s, %s) failed: %s", agent_id, platform, exc)
        return None


def save_session(agent_id: int, platform: str, storage_state: dict) -> None:
    """Encrypt and upsert storageState."""
    encrypted = _encrypt(json.dumps(storage_state))
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
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
    conn.close()


def save_credentials(agent_id: int, platform: str, username: str, password: str) -> None:
    """Encrypt and store login credentials."""
    enc_pass = _encrypt(password)
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
    conn.close()


def get_session_status(agent_id: int, platform: str) -> dict:
    """Return status dict for an agent/platform session."""
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
        conn.close()
        if not row:
            return {"status": "missing", "agent_id": agent_id, "platform": platform}
        return {
            "status": row["status"],
            "agent_id": agent_id,
            "platform": platform,
            "last_used": row["last_used_at"].isoformat() if row["last_used_at"] else None,
            "expires": row["session_expires_at"].isoformat() if row["session_expires_at"] else None,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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
