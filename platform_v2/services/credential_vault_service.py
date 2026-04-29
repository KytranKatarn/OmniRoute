"""credential_vault_service.py — encrypted credential storage for agent platform accounts.

Stores per-agent/user platform credentials encrypted with Fernet.
Vault key from CREDENTIAL_VAULT_KEY env var. Generate once:
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

_DEFAULT_SESSIONS_DIR = "/app/sessions"
_SENTINEL = object()


class CredentialVault:
    """Fernet-encrypted credential store for agent platform accounts."""

    def __init__(
        self,
        vault_key=_SENTINEL,
        sessions_dir: str = _DEFAULT_SESSIONS_DIR,
    ) -> None:
        if vault_key is _SENTINEL:
            vault_key = os.getenv("CREDENTIAL_VAULT_KEY")
            if not vault_key:
                raise ValueError(
                    "CREDENTIAL_VAULT_KEY not set. Generate with: "
                    'python3 -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"'
                )
        if vault_key is None:
            vault_key = Fernet.generate_key().decode()
        self._fernet = Fernet(vault_key.encode() if isinstance(vault_key, str) else vault_key)
        self._sessions_dir = sessions_dir
        Path(sessions_dir).mkdir(parents=True, exist_ok=True)

    def _encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

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
        """Store (insert or update) credentials. Returns row id."""
        if agent_id is None and user_id is None:
            raise ValueError("Pass either agent_id or user_id")

        encrypted = self._encrypt(password)
        update_clause = """
            email = EXCLUDED.email,
            encrypted_password = EXCLUDED.encrypted_password,
            platform_user_id = COALESCE(
                EXCLUDED.platform_user_id,
                agent_platform_accounts.platform_user_id
            ),
            managed_by_agent_id = COALESCE(
                EXCLUDED.managed_by_agent_id,
                agent_platform_accounts.managed_by_agent_id
            ),
            account_type = EXCLUDED.account_type
        """
        if agent_id is not None:
            conflict = "ON CONFLICT (agent_id, platform) DO UPDATE SET"
        else:
            conflict = "ON CONFLICT (user_id, platform) DO UPDATE SET"

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                f"""INSERT INTO agent_platform_accounts
                   (agent_id, user_id, platform, email, encrypted_password,
                    platform_user_id, managed_by_agent_id, account_type)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   {conflict}
                   {update_clause}
                   RETURNING id""",
                (
                    agent_id,
                    user_id,
                    platform,
                    email,
                    encrypted,
                    platform_user_id,
                    managed_by_agent_id,
                    account_type,
                ),
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
                    """SELECT * FROM agent_platform_accounts
                       WHERE agent_id=%s AND platform=%s AND is_active=TRUE""",
                    (agent_id, platform),
                )
            else:
                cur.execute(
                    """SELECT * FROM agent_platform_accounts
                       WHERE user_id=%s AND platform=%s AND is_active=TRUE""",
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
        """Update last_login_at timestamp."""
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE agent_platform_accounts SET last_login_at=NOW() WHERE id=%s",
                (account_id,),
            )

    def _cookie_path(self, account_id: int, platform: str) -> Path:
        return Path(self._sessions_dir) / f"{account_id}_{platform}.json"

    def save_session_cookies(self, account_id: int, platform: str, cookies: list[dict]) -> None:
        """Write cookies to disk and update session_cookie_path in DB."""
        path = self._cookie_path(account_id, platform)
        with open(path, "w") as f:
            json.dump(cookies, f)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE agent_platform_accounts SET session_cookie_path=%s WHERE id=%s",
                (str(path), account_id),
            )

    def load_session_cookies(self, account_id: int, platform: str) -> Optional[list[dict]]:
        """Load cookies from disk. Returns None if file doesn't exist."""
        path = self._cookie_path(account_id, platform)
        if not path.is_file():
            return None
        with open(path) as f:
            return json.load(f)


_vault: Optional[CredentialVault] = None


def get_vault() -> CredentialVault:
    """Return module-level CredentialVault singleton."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
