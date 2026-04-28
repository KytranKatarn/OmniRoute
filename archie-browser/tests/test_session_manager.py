import importlib
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.fernet import Fernet as _Fernet
os.environ.setdefault("BROWSER_ENCRYPTION_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def restore_real_session_manager():
    """Ensure the real session_manager module is loaded, not the MagicMock stub
    that create_app(testing=True) injects into sys.modules."""
    # Remove any mock stub placed by test_app.py
    sys.modules.pop("session_manager", None)
    # Force a clean import of the real module
    import session_manager as _sm_real
    sys.modules["session_manager"] = _sm_real
    yield
    # Leave real module in place for subsequent tests in this file


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        import session_manager
        plaintext = '{"cookies": [{"name": "session", "value": "abc123"}]}'
        encrypted = session_manager._encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = session_manager._decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertext_each_time(self):
        import session_manager
        text = "same plaintext"
        enc1 = session_manager._encrypt(text)
        enc2 = session_manager._encrypt(text)
        assert enc1 != enc2

    def test_decrypt_wrong_key_raises(self):
        import session_manager
        from cryptography.fernet import Fernet, InvalidToken
        encrypted = session_manager._encrypt("secret")
        orig = os.environ.get("BROWSER_ENCRYPTION_KEY", "")
        try:
            os.environ["BROWSER_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
            session_manager._fernet_cache.clear()
            with pytest.raises((InvalidToken, Exception)):
                session_manager._decrypt(encrypted)
        finally:
            os.environ["BROWSER_ENCRYPTION_KEY"] = orig
            session_manager._fernet_cache.clear()


class TestGetSessionStatus:
    def test_get_session_status_missing(self):
        """Mock DB returns no row → {status: 'missing', last_used: None}."""
        import session_manager

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur

        with patch("session_manager._get_conn", return_value=mock_conn):
            result = session_manager.get_session_status(42, "linkedin")

        assert result["status"] == "missing"
        assert result["last_used"] is None

    def test_get_session_status_active(self):
        """Mock DB returns a row → status and fields returned correctly."""
        import session_manager
        from datetime import datetime, timezone

        now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "status": "active",
            "last_used_at": now,
            "session_expires_at": None,
        }
        mock_conn.cursor.return_value = mock_cur

        with patch("session_manager._get_conn", return_value=mock_conn):
            result = session_manager.get_session_status(42, "linkedin")

        assert result["status"] == "active"
        assert result["last_used"] == now.isoformat()
        assert result["expires_at"] is None


class TestRefreshSession:
    def test_refresh_session_no_credentials(self):
        """get_credentials returns None → {success: False}."""
        import session_manager

        with patch("session_manager.get_credentials", return_value=None):
            result = session_manager.refresh_session(42, "linkedin")

        assert result["success"] is False
        assert "error" in result

    def test_refresh_session_with_credentials(self):
        """get_credentials returns creds → {success: True, message: 'refresh_pending'}."""
        import session_manager

        creds = {"username": "agent@example.com", "password": "s3cr3t"}
        with patch("session_manager.get_credentials", return_value=creds):
            result = session_manager.refresh_session(42, "linkedin")

        assert result["success"] is True
        assert result["message"] == "refresh_pending"
        assert result["agent_id"] == 42
        assert result["platform"] == "linkedin"
