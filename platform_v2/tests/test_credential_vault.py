"""Tests for credential_vault_service.py

Run: docker exec archie_platform python -m pytest tests/test_credential_vault.py -v
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestEncryption:
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

        with patch("services.credential_vault_service.get_db_cursor") as mock_db:
            mock_cur = MagicMock()
            mock_cur.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_cur.__exit__ = MagicMock(return_value=False)
            mock_db.return_value = mock_cur
            vault.save_session_cookies(account_id=1, platform="linkedin", cookies=cookies)

        loaded = vault.load_session_cookies(account_id=1, platform="linkedin")
        assert loaded == cookies
        assert (tmp_path / "1_linkedin.json").is_file()

    def test_load_returns_none_when_no_cookies(self, tmp_path):
        """load_session_cookies returns None when no cookie file exists."""
        from services.credential_vault_service import CredentialVault

        vault = CredentialVault(vault_key=None, sessions_dir=str(tmp_path))
        assert vault.load_session_cookies(account_id=99, platform="linkedin") is None

    def test_raises_value_error_without_owner(self):
        """store_credentials raises ValueError when neither agent_id nor user_id is given."""
        from services.credential_vault_service import CredentialVault
        from unittest.mock import patch

        vault = CredentialVault(vault_key=None)
        with patch("services.credential_vault_service.get_db_cursor"):
            with pytest.raises(ValueError, match="agent_id or user_id"):
                vault.store_credentials(platform="linkedin", email="a@b.com", password="pw")
