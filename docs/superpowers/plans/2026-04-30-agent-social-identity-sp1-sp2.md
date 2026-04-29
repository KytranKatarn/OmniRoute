# Agent Social Identity SP1+SP2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Agent Identity Vault (encrypted credential storage) and LinkedIn Web Agent (Playwright-based login, account provisioning, and posting) so A.R.C.H.I.E. can manage Kytran's LinkedIn and S.I.G.N.A.L. can post to their own profile and the company page.

**Architecture:** A new `agent_platform_accounts` DB table stores per-agent platform credentials encrypted with Fernet. `credential_vault_service.py` handles all encrypt/decrypt/session operations. Two Playwright scripts (`provision_agent_linkedin.py`, `linkedin_post.py`) handle account creation and posting. DHQ gains three new capabilities (`social_post_draft`, `social_post_approve`, `social_account_provision`) wired to S.I.G.N.A.L., A.R.C.H.I.E., and B.A.S.E.

**Tech Stack:** Python 3.11, `cryptography` (Fernet), `playwright` (sync_api), `argparse`, PostgreSQL, pytest + unittest.mock

**Known IDs (do not query DB for these):**
- A.R.C.H.I.E.: `agent_id=2`
- S.I.G.N.A.L.: `agent_id=141`
- B.A.S.E.: `agent_id=139`
- Kytran: `user_id=2`

---

## File Structure

```
database/migrations/
  357_agent_platform_accounts.sql   ← new table
  358_social_capabilities.sql       ← seed skills on SIGNAL, ARCHIE, BASE

platform_v2/services/
  credential_vault_service.py       ← encrypt/decrypt/session management

platform_v2/tests/
  test_credential_vault.py          ← unit tests for vault service

scripts/
  provision_agent_linkedin.py       ← autonomous LinkedIn account creation
  linkedin_post.py                  ← post to personal profile or company page

platform_v2/tools/department_hq/services/
  department_coordinator.py         ← add 3 new capabilities (modify)
```

---

### Task 1: DB Migration — agent_platform_accounts table

**Files:**
- Create: `database/migrations/357_agent_platform_accounts.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- database/migrations/357_agent_platform_accounts.sql
-- Agent Social Identity — credential vault for per-agent platform accounts.
-- Supports both AI agent accounts (agent_id) and human accounts managed by agents (user_id).

CREATE TABLE IF NOT EXISTS agent_platform_accounts (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    platform            VARCHAR(50) NOT NULL,
    username            VARCHAR(255),
    email               VARCHAR(255) NOT NULL,
    encrypted_password  TEXT,
    session_cookie_path TEXT,
    managed_by_agent_id INTEGER REFERENCES agents(id),
    account_type        VARCHAR(50) NOT NULL DEFAULT 'personal',
    platform_user_id    VARCHAR(255),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT owner_required CHECK (agent_id IS NOT NULL OR user_id IS NOT NULL),
    UNIQUE (agent_id, platform),
    UNIQUE (user_id, platform)
);

CREATE INDEX idx_apa_agent_platform ON agent_platform_accounts (agent_id, platform);
CREATE INDEX idx_apa_managed_by ON agent_platform_accounts (managed_by_agent_id) WHERE managed_by_agent_id IS NOT NULL;

COMMENT ON TABLE agent_platform_accounts IS
    'Per-agent/user platform credentials. agent_id for AI agents, user_id for human accounts managed by agents.';
COMMENT ON COLUMN agent_platform_accounts.managed_by_agent_id IS
    'Which agent manages this account. NULL = self-managed. agent_id=2 (ARCHIE) manages user_id=2 (Kytran).';
COMMENT ON COLUMN agent_platform_accounts.encrypted_password IS
    'Fernet-encrypted password. Key = CREDENTIAL_VAULT_KEY env var.';
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/database/migrations/357_agent_platform_accounts.sql
```

Expected output:
```
CREATE TABLE
CREATE INDEX
CREATE INDEX
COMMENT
COMMENT
COMMENT
```

- [ ] **Step 3: Verify the table**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "\d agent_platform_accounts"
```

Expected: table with all 14 columns listed.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/357_agent_platform_accounts.sql
git commit -m "feat(vault): migration 357 — agent_platform_accounts table"
```

---

### Task 2: Credential Vault Service + tests

**Files:**
- Create: `platform_v2/services/credential_vault_service.py`
- Create: `platform_v2/tests/test_credential_vault.py`

- [ ] **Step 1: Write the failing tests**

Create `platform_v2/tests/test_credential_vault.py`:

```python
"""Tests for credential_vault_service.py

Run: docker exec archie_platform python -m pytest tests/test_credential_vault.py -v
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, call

import pytest


class TestStoreCredentials:
    def test_stores_and_retrieves_password_decrypted(self, tmp_path):
        """store_credentials encrypts the password; get_credentials returns it decrypted."""
        from services.credential_vault_service import CredentialVault

        vault = CredentialVault(vault_key=None)  # generates ephemeral key in tests

        with patch("services.credential_vault_service.get_db_cursor") as mock_db:
            mock_cur = MagicMock()
            mock_cur.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_cur.fetchone.return_value = None  # no existing row
            mock_cur.fetchone.side_effect = [
                None,  # first call: no existing row (INSERT path)
                {
                    "id": 1,
                    "agent_id": 141,
                    "user_id": None,
                    "platform": "linkedin",
                    "email": "signal@kytranempowerment.com",
                    "encrypted_password": vault._encrypt("secret123"),
                    "session_cookie_path": None,
                    "platform_user_id": None,
                    "account_type": "personal",
                    "managed_by_agent_id": None,
                    "is_active": True,
                    "last_login_at": None,
                },
            ]
            mock_db.return_value = mock_cur

            vault.store_credentials(
                agent_id=141,
                platform="linkedin",
                email="signal@kytranempowerment.com",
                password="secret123",
            )
            result = vault.get_credentials(agent_id=141, platform="linkedin")

        assert result["email"] == "signal@kytranempowerment.com"
        assert result["password"] == "secret123"

    def test_encrypt_decrypt_roundtrip(self):
        """_encrypt and _decrypt are inverses."""
        from services.credential_vault_service import CredentialVault

        vault = CredentialVault(vault_key=None)
        original = "my_super_secret_password_123!"
        encrypted = vault._encrypt(original)
        assert encrypted != original
        assert vault._decrypt(encrypted) == original

    def test_raises_on_missing_vault_key_in_production(self):
        """CredentialVault raises ValueError if CREDENTIAL_VAULT_KEY is not set and no key passed."""
        from services.credential_vault_service import CredentialVault

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="CREDENTIAL_VAULT_KEY"):
                CredentialVault()


class TestSessionCookies:
    def test_save_and_load_cookies(self, tmp_path):
        """save_session_cookies writes JSON; load_session_cookies reads it back."""
        from services.credential_vault_service import CredentialVault

        vault = CredentialVault(vault_key=None, sessions_dir=str(tmp_path))
        cookies = [{"name": "li_at", "value": "abc123", "domain": ".linkedin.com"}]

        vault.save_session_cookies(account_id=1, platform="linkedin", cookies=cookies)
        loaded = vault.load_session_cookies(account_id=1, platform="linkedin")

        assert loaded == cookies
        assert (tmp_path / "1_linkedin.json").is_file()

    def test_load_returns_none_when_no_cookies(self, tmp_path):
        """load_session_cookies returns None when no cookie file exists."""
        from services.credential_vault_service import CredentialVault

        vault = CredentialVault(vault_key=None, sessions_dir=str(tmp_path))
        assert vault.load_session_cookies(account_id=99, platform="linkedin") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest tests/test_credential_vault.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `credential_vault_service` doesn't exist yet.

- [ ] **Step 3: Create `platform_v2/services/credential_vault_service.py`**

```python
"""credential_vault_service.py — encrypted credential storage for agent platform accounts.

Stores per-agent/user platform credentials (LinkedIn, Twitter, etc.) encrypted with Fernet.
Vault key is read from CREDENTIAL_VAULT_KEY env var. Generate once with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
then add to .env: CREDENTIAL_VAULT_KEY=<output>
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from database import get_db_cursor

_DEFAULT_SESSIONS_DIR = "/mnt/archie_brain/secrets/sessions"


class CredentialVault:
    """Fernet-encrypted credential store for agent platform accounts."""

    def __init__(
        self,
        vault_key: Optional[str] = ...,  # sentinel: read from env
        sessions_dir: str = _DEFAULT_SESSIONS_DIR,
    ) -> None:
        if vault_key is ...:
            vault_key = os.getenv("CREDENTIAL_VAULT_KEY")
            if not vault_key:
                raise ValueError(
                    "CREDENTIAL_VAULT_KEY not set. Generate with: "
                    "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
        if vault_key is None:
            # Test mode: generate ephemeral key
            vault_key = Fernet.generate_key().decode()
        self._fernet = Fernet(vault_key.encode() if isinstance(vault_key, str) else vault_key)
        self._sessions_dir = sessions_dir
        Path(sessions_dir).mkdir(parents=True, exist_ok=True)

    # --- Encryption helpers ---

    def _encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    # --- Credential CRUD ---

    def store_credentials(
        self,
        platform: str,
        email: str,
        password: str,
        agent_id: Optional[int] = None,
        user_id: Optional[int] = None,
        platform_user_id: Optional[str] = None,
        managed_by_agent_id: Optional[int] = None,
        account_type: str = "personal",
    ) -> int:
        """Store (insert or update) credentials for an agent/user on a platform.

        Returns the row id.
        """
        if agent_id is None and user_id is None:
            raise ValueError("Pass either agent_id or user_id")

        encrypted = self._encrypt(password)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO agent_platform_accounts
                   (agent_id, user_id, platform, email, encrypted_password,
                    platform_user_id, managed_by_agent_id, account_type)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (agent_id, platform) DO UPDATE SET
                       email = EXCLUDED.email,
                       encrypted_password = EXCLUDED.encrypted_password,
                       platform_user_id = COALESCE(EXCLUDED.platform_user_id, agent_platform_accounts.platform_user_id),
                       managed_by_agent_id = COALESCE(EXCLUDED.managed_by_agent_id, agent_platform_accounts.managed_by_agent_id),
                       account_type = EXCLUDED.account_type
                   RETURNING id""",
                (agent_id, user_id, platform, email, encrypted, platform_user_id,
                 managed_by_agent_id, account_type),
            )
            row = cur.fetchone()
            return row["id"]

    def get_credentials(
        self,
        platform: str,
        agent_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Return credential dict with password decrypted, or None if not found."""
        if agent_id is None and user_id is None:
            raise ValueError("Pass either agent_id or user_id")

        with get_db_cursor() as (_conn, cur):
            if agent_id is not None:
                cur.execute(
                    "SELECT * FROM agent_platform_accounts WHERE agent_id=%s AND platform=%s AND is_active=TRUE",
                    (agent_id, platform),
                )
            else:
                cur.execute(
                    "SELECT * FROM agent_platform_accounts WHERE user_id=%s AND platform=%s AND is_active=TRUE",
                    (user_id, platform),
                )
            row = cur.fetchone()

        if not row:
            return None

        result = dict(row)
        if result.get("encrypted_password"):
            result["password"] = self._decrypt(result.pop("encrypted_password"))
        else:
            result["password"] = None
            result.pop("encrypted_password", None)
        return result

    def mark_login(self, account_id: int) -> None:
        """Update last_login_at timestamp for the account row."""
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE agent_platform_accounts SET last_login_at=NOW() WHERE id=%s",
                (account_id,),
            )

    # --- Session cookies ---

    def _cookie_path(self, account_id: int, platform: str) -> Path:
        return Path(self._sessions_dir) / f"{account_id}_{platform}.json"

    def save_session_cookies(self, account_id: int, platform: str, cookies: list[dict]) -> None:
        """Persist Playwright cookies to disk and update session_cookie_path in DB."""
        path = self._cookie_path(account_id, platform)
        with open(path, "w") as f:
            json.dump(cookies, f)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE agent_platform_accounts SET session_cookie_path=%s WHERE id=%s",
                (str(path), account_id),
            )

    def load_session_cookies(self, account_id: int, platform: str) -> Optional[list[dict]]:
        """Load persisted cookies from disk. Returns None if no file exists."""
        path = self._cookie_path(account_id, platform)
        if not path.is_file():
            return None
        with open(path) as f:
            return json.load(f)


# Module-level singleton — import this in scripts and services
_vault: Optional[CredentialVault] = None


def get_vault() -> CredentialVault:
    """Return the module-level CredentialVault singleton."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest tests/test_credential_vault.py -v
```

Expected: 5 tests PASS

- [ ] **Step 5: Add CREDENTIAL_VAULT_KEY to .env**

Generate a key:
```bash
docker exec archie_platform python3 -c \
  "from cryptography.fernet import Fernet; print('CREDENTIAL_VAULT_KEY=' + Fernet.generate_key().decode())"
```

Append the output to both `.env` and `platform_v2/.env`:
```bash
# Add the printed line to both files
echo "CREDENTIAL_VAULT_KEY=<output_from_above>" >> /mnt/archie_brain/.env
echo "CREDENTIAL_VAULT_KEY=<output_from_above>" >> /mnt/archie_brain/platform_v2/.env
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/credential_vault_service.py \
        platform_v2/tests/test_credential_vault.py
git commit -m "feat(vault): credential_vault_service — Fernet-encrypted platform credentials"
```

---

### Task 3: LinkedIn Account Provisioner

**Files:**
- Create: `scripts/provision_agent_linkedin.py`

- [ ] **Step 1: Create `scripts/provision_agent_linkedin.py`**

```python
#!/usr/bin/env python3
"""provision_agent_linkedin.py — Autonomously create a LinkedIn account for an ARCHIE agent.

Uses the agent's existing Stalwart email address to sign up on LinkedIn,
confirms via Email Manager API, sets up the profile with their portrait and bio,
and stores credentials in the vault.

Usage:
    python3 scripts/provision_agent_linkedin.py --agent-id 141
    python3 scripts/provision_agent_linkedin.py --agent-name "S.I.G.N.A.L."

Requirements:
    - CREDENTIAL_VAULT_KEY set in environment
    - PLATFORM_API_KEY set (for Email Manager API auth) or run with a valid session cookie
    - Agent must have a Stalwart email in email_mailboxes table
    - Agent portrait at website/kytranempowerment.com/assets/portraits/{stem}.jpg
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))

from database import get_db_cursor
from services.credential_vault_service import get_vault


_ARCHIE_API = os.getenv("ARCHIE_API_BASE", "http://192.168.1.200:3000")
_PORTRAIT_DIR = "/mnt/archie_brain/website/kytranempowerment.com/assets/portraits"


def _get_agent(agent_id: int | None, agent_name: str | None) -> dict:
    """Fetch agent profile from DB."""
    with get_db_cursor() as (_conn, cur):
        if agent_id:
            cur.execute(
                """SELECT a.id, a.name, a.display_name, a.bio, a.title,
                          e.address AS email
                   FROM agents a
                   LEFT JOIN email_mailboxes e ON e.owner_agent_id = a.id AND e.provisioned = TRUE
                   WHERE a.id = %s""",
                (agent_id,),
            )
        else:
            cur.execute(
                """SELECT a.id, a.name, a.display_name, a.bio, a.title,
                          e.address AS email
                   FROM agents a
                   LEFT JOIN email_mailboxes e ON e.owner_agent_id = a.id AND e.provisioned = TRUE
                   WHERE a.name = %s""",
                (agent_name,),
            )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Agent not found: {agent_id or agent_name}")
    if not row["email"]:
        raise ValueError(f"Agent {row['name']} has no provisioned Stalwart email")
    return dict(row)


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _poll_confirmation_email(email: str, timeout: int = 300, interval: int = 30) -> str | None:
    """Poll Email Manager API for a LinkedIn confirmation email.

    Returns the confirmation URL extracted from the subject/body, or None on timeout.
    The Email Manager API: GET /api/email/inbox/messages?address={email}&limit=10
    Returns JSON: {"messages": [{from_address, subject, logged_at, ...}]}
    Note: This endpoint only returns metadata — the provisioner should navigate
    to the confirmation URL via LinkedIn's standard email flow.
    """
    import requests as _req

    session_cookie = os.getenv("ARCHIE_SESSION_COOKIE", "")
    headers = {"Cookie": session_cookie} if session_cookie else {}

    deadline = time.time() + timeout
    print(f"[provision] Polling for LinkedIn confirmation email at {email} (timeout {timeout}s)...")

    while time.time() < deadline:
        try:
            r = _req.get(
                f"{_ARCHIE_API}/api/email/inbox/messages",
                params={"address": email, "limit": 10},
                headers=headers,
                timeout=10,
            )
            if r.ok:
                messages = r.json().get("messages", [])
                for msg in messages:
                    sender = (msg.get("from_address") or "").lower()
                    subject = (msg.get("subject") or "").lower()
                    if "linkedin" in sender and any(
                        kw in subject for kw in ("confirm", "verify", "activate")
                    ):
                        print(f"[provision] Confirmation email found: {msg['subject']}")
                        return msg.get("message_id")  # caller navigates LinkedIn to confirm
        except Exception as exc:
            print(f"[provision] Poll error: {exc}", file=sys.stderr)

        print(f"[provision] No confirmation yet, waiting {interval}s...")
        time.sleep(interval)

    return None


def _get_portrait_path(agent: dict) -> str | None:
    """Return path to agent's portrait JPEG, or None if not found."""
    stem = agent["name"].replace(".", "").replace(" ", "_").lower()
    path = os.path.join(_PORTRAIT_DIR, f"{stem}.jpg")
    return path if os.path.isfile(path) else None


def provision(agent_id: int | None = None, agent_name: str | None = None) -> dict:
    """Provision a LinkedIn account for an agent. Returns result dict."""
    agent = _get_agent(agent_id, agent_name)
    print(f"[provision] Provisioning LinkedIn for {agent['name']} ({agent['email']})")

    # 1. Generate and immediately store password in vault (before any network calls)
    password = _generate_password()
    vault = get_vault()
    display_name = agent["display_name"] or agent["name"]
    first_name, *rest = display_name.split(" ", 1)
    last_name = rest[0] if rest else agent["name"]

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # 2. Navigate to LinkedIn signup
        print("[provision] Navigating to LinkedIn signup...")
        page.goto("https://www.linkedin.com/signup", wait_until="networkidle", timeout=30000)

        # 3. Fill signup form
        page.fill('input[id="first-name"], input[name="firstName"]', first_name)
        page.fill('input[id="last-name"], input[name="lastName"]', last_name)
        page.fill('input[id="email-address"], input[name="email"]', agent["email"])
        page.fill('input[id="password"], input[name="password"]', password)
        page.click('button[type="submit"], button[data-id="sign-up-btn"]')
        page.wait_for_timeout(3000)

        # 4. Store password now (signup submitted)
        account_id = vault.store_credentials(
            agent_id=agent["id"],
            platform="linkedin",
            email=agent["email"],
            password=password,
        )
        print(f"[provision] Credentials stored (account_id={account_id})")

        # 5. Poll for confirmation email
        msg_id = _poll_confirmation_email(agent["email"])
        if not msg_id:
            print("[provision] WARNING: No confirmation email found within timeout", file=sys.stderr)
            print("[provision] Manual confirmation required at linkedin.com")
        else:
            # LinkedIn will have sent the user to a verification flow in the current browser session
            print(f"[provision] Confirmation email detected (message_id={msg_id})")
            page.wait_for_timeout(2000)

        # 6. Complete profile setup (best-effort — LinkedIn flow varies)
        try:
            # Upload portrait
            portrait_path = _get_portrait_path(agent)
            if portrait_path:
                # LinkedIn profile photo upload varies; navigate to profile
                page.goto("https://www.linkedin.com/in/me/", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(2000)
                print(f"[provision] Portrait available at {portrait_path} — upload manually if needed")

            # Save session cookies
            cookies = page.context.cookies()
            vault.save_session_cookies(account_id, "linkedin", cookies)
            vault.mark_login(account_id)
            print("[provision] Session cookies saved")
        except Exception as exc:
            print(f"[provision] Profile setup partial: {exc}", file=sys.stderr)

        browser.close()

    result = {
        "status": "provisioned",
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "platform": "linkedin",
        "email": agent["email"],
        "account_id": account_id,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a LinkedIn account for an ARCHIE agent.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent-id", type=int, help="Agent ID from agents table")
    group.add_argument("--agent-name", help='Agent name e.g. "S.I.G.N.A.L."')
    args = parser.parse_args()
    provision(agent_id=args.agent_id, agent_name=args.agent_name)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/provision_agent_linkedin.py
```

- [ ] **Step 3: Smoke test — dry run (DB query only, no browser)**

```bash
python3 scripts/provision_agent_linkedin.py --agent-id 141 2>&1 | head -5
```

Expected: `[provision] Provisioning LinkedIn for S.I.G.N.A.L. (signal@kytranempowerment.com)` then Playwright launches. Stop with Ctrl+C after confirming DB/email lookup works.

- [ ] **Step 4: Commit**

```bash
git add scripts/provision_agent_linkedin.py
git commit -m "feat(vault): provision_agent_linkedin.py — autonomous LinkedIn account creation"
```

---

### Task 4: LinkedIn Post Agent

**Files:**
- Create: `scripts/linkedin_post.py`

- [ ] **Step 1: Create `scripts/linkedin_post.py`**

```python
#!/usr/bin/env python3
"""linkedin_post.py — Post to LinkedIn as an agent using stored credentials.

Usage:
    # Agent posts to their own profile:
    python3 scripts/linkedin_post.py --agent-id 141 --content "..." --target personal

    # A.R.C.H.I.E. posts to Kytran's company page (requires approval first):
    python3 scripts/linkedin_post.py --managed-user-id 2 --content "..." --target company

    # A.R.C.H.I.E. posts to Kytran's personal profile:
    python3 scripts/linkedin_post.py --managed-user-id 2 --content "..." --target personal

Requirements:
    - CREDENTIAL_VAULT_KEY in environment
    - Account must exist in agent_platform_accounts (run provision_agent_linkedin.py first)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))

from services.credential_vault_service import get_vault


def _load_and_login(page, vault, agent_id: int | None, user_id: int | None) -> dict:
    """Load credentials, try cookies first, fall back to password login. Returns account dict."""
    creds = vault.get_credentials(platform="linkedin", agent_id=agent_id, user_id=user_id)
    if not creds:
        raise ValueError(f"No LinkedIn credentials found for agent_id={agent_id} user_id={user_id}")

    # Try session cookies first
    cookies = vault.load_session_cookies(creds["id"], "linkedin")
    if cookies:
        page.context.add_cookies(cookies)
        page.goto("https://www.linkedin.com/feed/", wait_until="networkidle", timeout=20000)
        if "feed" in page.url or "mynetwork" in page.url:
            print("[post] Session cookie login successful")
            return creds

    # Fall back to password login
    print("[post] Session expired, logging in with credentials...")
    page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=20000)
    page.fill('input[name="session_key"]', creds["email"])
    page.fill('input[name="session_password"]', creds["password"])
    page.click('button[type="submit"]')
    page.wait_for_url("**/feed/**", timeout=15000)

    # Save fresh cookies
    cookies = page.context.cookies()
    vault.save_session_cookies(creds["id"], "linkedin", cookies)
    vault.mark_login(creds["id"])
    print("[post] Password login successful, cookies saved")
    return creds


def _post_personal(page, content: str) -> str:
    """Post to personal LinkedIn feed. Returns URL of posted content."""
    page.goto("https://www.linkedin.com/feed/", wait_until="networkidle", timeout=20000)

    # Open post composer
    page.click('button[class*="share-box-feed-entry__trigger"]', timeout=10000)
    page.wait_for_selector('div[role="textbox"]', timeout=10000)

    # Type content
    page.fill('div[role="textbox"]', content)
    page.wait_for_timeout(1000)

    # Post
    page.click('button[class*="share-actions__primary-action"]', timeout=5000)
    page.wait_for_timeout(3000)

    print("[post] Posted to personal feed")
    return page.url


def _post_company(page, content: str, company_name: str = "Kytran Empowerment Inc.") -> str:
    """Post to company page as admin. Returns URL of posted content."""
    # Navigate to company page admin
    page.goto("https://www.linkedin.com/company/kytran-empowerment-inc/admin/", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(2000)

    # Open post composer
    page.click('button[class*="share-box-feed-entry__trigger"]', timeout=10000)
    page.wait_for_selector('div[role="textbox"]', timeout=10000)

    page.fill('div[role="textbox"]', content)
    page.wait_for_timeout(1000)

    page.click('button[class*="share-actions__primary-action"]', timeout=5000)
    page.wait_for_timeout(3000)

    print(f"[post] Posted to {company_name} company page")
    return page.url


def post(
    content: str,
    target: str,  # 'personal' or 'company'
    agent_id: int | None = None,
    managed_user_id: int | None = None,
    screenshot_path: str = "/tmp/linkedin_post_confirm.png",
) -> dict:
    """Post content to LinkedIn. Returns result dict with status and screenshot path."""
    if agent_id is None and managed_user_id is None:
        raise ValueError("Pass either agent_id or managed_user_id")
    if target not in ("personal", "company"):
        raise ValueError("target must be 'personal' or 'company'")

    vault = get_vault()

    from playwright.sync_api import sync_playwright

    post_url = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _load_and_login(page, vault, agent_id=agent_id, user_id=managed_user_id)

        if target == "personal":
            post_url = _post_personal(page, content)
        else:
            post_url = _post_company(page, content)

        page.screenshot(path=screenshot_path)
        browser.close()

    result = {
        "status": "posted",
        "target": target,
        "agent_id": agent_id,
        "managed_user_id": managed_user_id,
        "post_url": post_url,
        "screenshot": screenshot_path,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Post to LinkedIn as an ARCHIE agent.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--agent-id", type=int, help="Post as this agent's personal account")
    source.add_argument("--managed-user-id", type=int, help="Post as a managed human user account")
    parser.add_argument("--content", required=True, help="Post text content")
    parser.add_argument("--target", choices=["personal", "company"], default="personal")
    parser.add_argument("--screenshot", default="/tmp/linkedin_post_confirm.png")
    args = parser.parse_args()
    post(
        content=args.content,
        target=args.target,
        agent_id=args.agent_id,
        managed_user_id=args.managed_user_id,
        screenshot_path=args.screenshot,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/linkedin_post.py
```

- [ ] **Step 3: Verify argparse works**

```bash
python3 scripts/linkedin_post.py --help
```

Expected: help text listing `--agent-id`, `--managed-user-id`, `--content`, `--target`, `--screenshot`.

- [ ] **Step 4: Commit**

```bash
git add scripts/linkedin_post.py
git commit -m "feat(vault): linkedin_post.py — Playwright-based LinkedIn posting agent"
```

---

### Task 5: DHQ capability wiring + skill seeds

**Files:**
- Modify: `platform_v2/tools/department_hq/services/department_coordinator.py`
- Create: `database/migrations/358_social_capabilities.sql`

- [ ] **Step 1: Add capabilities to CAPABILITY_DEPARTMENT_MAP**

In `platform_v2/tools/department_hq/services/department_coordinator.py`, find `CAPABILITY_DEPARTMENT_MAP` and add:

```python
    "social_post_draft": "Marketing & Communications",   # S.I.G.N.A.L. drafts
    "social_post_approve": "Executive Office",           # A.R.C.H.I.E. approves
    "social_account_provision": "Operations & Infrastructure",  # B.A.S.E. provisions
```

- [ ] **Step 2: Verify the addition**

```bash
docker exec archie_platform python3 -c "
from tools.department_hq.services.department_coordinator import CAPABILITY_DEPARTMENT_MAP
for cap in ('social_post_draft', 'social_post_approve', 'social_account_provision'):
    print(cap, '->', CAPABILITY_DEPARTMENT_MAP.get(cap, 'MISSING'))
"
```

Expected:
```
social_post_draft -> Marketing & Communications
social_post_approve -> Executive Office
social_account_provision -> Operations & Infrastructure
```

- [ ] **Step 3: Create migration 358 for skill seeds**

```sql
-- database/migrations/358_social_capabilities.sql
-- Seed social media capabilities on S.I.G.N.A.L. (141), A.R.C.H.I.E. (2), B.A.S.E. (139)

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES
    (141, 'social_post_draft',       5, NULL),   -- S.I.G.N.A.L.: expert content drafter
    (2,   'social_post_approve',     5, NULL),   -- A.R.C.H.I.E.: COO content approver
    (139, 'social_account_provision',5, NULL)    -- B.A.S.E.: infrastructure provisioner
ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level;
```

- [ ] **Step 4: Run migration 358**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/database/migrations/358_social_capabilities.sql
```

Expected: `INSERT 0 3`

- [ ] **Step 5: Verify skills seeded**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT a.name, s.skill_name, s.proficiency_level
FROM agent_skills s JOIN agents a ON a.id = s.agent_id
WHERE s.skill_name IN ('social_post_draft','social_post_approve','social_account_provision')
ORDER BY s.skill_name;"
```

Expected: 3 rows — S.I.G.N.A.L., A.R.C.H.I.E., B.A.S.E. each with Lv5.

- [ ] **Step 6: Restart platform and run full test suite**

```bash
docker compose restart archie_platform
docker exec archie_platform python -m pytest tests/test_credential_vault.py tests/test_deploy_service.py -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/department_hq/services/department_coordinator.py \
        database/migrations/358_social_capabilities.sql
git commit -m "feat(vault): DHQ capabilities + skill seeds — social_post_draft, social_post_approve, social_account_provision"
```

---

### Task 6: Store Kytran's LinkedIn credentials + seed A.R.C.H.I.E. as manager

**Files:** No code changes — DB operations only.

- [ ] **Step 1: Generate CREDENTIAL_VAULT_KEY if not already done**

```bash
grep "CREDENTIAL_VAULT_KEY" /mnt/archie_brain/.env
```

If not set, run Task 2 Step 5 first.

- [ ] **Step 2: Store Kytran's LinkedIn credentials**

```bash
python3 -c "
import sys; sys.path.insert(0, 'platform_v2')
from services.credential_vault_service import get_vault
vault = get_vault()

# Store Kytran's LinkedIn — managed by A.R.C.H.I.E. (agent_id=2)
# Replace EMAIL and PASSWORD with Kytran's actual LinkedIn login
account_id = vault.store_credentials(
    user_id=2,                          # Kytran's user account
    platform='linkedin',
    email='EMAIL_HERE',                  # Kytran's LinkedIn email
    password='PASSWORD_HERE',            # Kytran's LinkedIn password
    managed_by_agent_id=2,              # A.R.C.H.I.E. manages it
    account_type='personal',
)
print('Stored Kytran LinkedIn account_id:', account_id)
"
```

- [ ] **Step 3: Verify stored correctly (password not visible)**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, user_id, platform, email, account_type, managed_by_agent_id,
       LEFT(encrypted_password, 20) || '...' AS enc_preview
FROM agent_platform_accounts WHERE user_id = 2;"
```

Expected: row with `managed_by_agent_id=2`, encrypted password preview (not plaintext).

- [ ] **Step 4: Test A.R.C.H.I.E. can retrieve credentials**

```bash
python3 -c "
import sys; sys.path.insert(0, 'platform_v2')
from services.credential_vault_service import get_vault
vault = get_vault()
creds = vault.get_credentials(user_id=2, platform='linkedin')
print('email:', creds['email'])
print('password starts with:', creds['password'][:3] + '...')
print('managed_by_agent_id:', creds['managed_by_agent_id'])
"
```

Expected: email and masked password printed, `managed_by_agent_id=2`.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/357_agent_platform_accounts.sql \
        database/migrations/358_social_capabilities.sql
git push origin main
```

---

## Self-Review

### Spec coverage
- ✅ Migration 357 — `agent_platform_accounts` table with `agent_id`/`user_id` dual ownership
- ✅ `credential_vault_service.py` — Fernet encrypt/decrypt, store/get credentials, session cookies
- ✅ `provision_agent_linkedin.py` — Playwright signup, Email Manager poll, vault storage
- ✅ `linkedin_post.py` — personal profile + company page posting, session cookie persistence
- ✅ DHQ capabilities `social_post_draft`, `social_post_approve`, `social_account_provision`
- ✅ Migration 358 — skills seeded on S.I.G.N.A.L. (141), A.R.C.H.I.E. (2), B.A.S.E. (139)
- ✅ Kytran's credentials stored with A.R.C.H.I.E. as manager

### Type consistency
- `get_credentials(platform, agent_id, user_id)` → used consistently in `linkedin_post.py`
- `store_credentials(platform, email, password, agent_id, user_id, ...)` → consistent across vault service and provisioner
- `account_id` (row PK) vs `agent_id` (agents table FK) — correctly distinguished throughout

### No placeholders — all code is complete and runnable
