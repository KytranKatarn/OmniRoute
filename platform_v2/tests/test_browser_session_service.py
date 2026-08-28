"""Unit tests for services.browser_session_service (Layer A Phase 1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_cursor(row=None, rows=None):
    """Mock context manager for get_db_cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    cm = _CM()
    cm.cursor = cur
    return cm


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Service expects BROWSER_ENCRYPTION_KEY env. Use a fixed test key."""
    monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")


@pytest.fixture
def svc():
    from services import browser_session_service

    return browser_session_service


class TestEncryptionPrimitives:
    def test_encrypt_decrypt_round_trip(self, svc):
        original = {"cookies": [{"name": "li_at", "value": "secret-token"}]}
        ciphertext = svc.encrypt_state(original)
        assert isinstance(ciphertext, bytes)
        assert b"secret-token" not in ciphertext  # confirm it IS encrypted
        recovered = svc.decrypt_state(ciphertext)
        assert recovered == original

    def test_decrypt_with_wrong_key_raises(self, svc, monkeypatch):
        ciphertext = svc.encrypt_state({"x": 1})
        monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "ffffffffffffffffffffffffffffffff")
        # Reload module so it picks up new key
        import importlib

        import services.browser_session_service as m

        importlib.reload(m)
        with pytest.raises(Exception):
            m.decrypt_state(ciphertext)

    def test_encrypt_handles_unicode(self, svc):
        original = {"text": "Bonjour 🇨🇦 — Québécois français"}
        recovered = svc.decrypt_state(svc.encrypt_state(original))
        assert recovered == original


class TestSaveSession:
    def test_upserts_row_with_active_status(self, svc):
        cm = _mock_cursor(row={"id": 1})
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            result = svc.save_session(agent_id=7, platform="linkedin", state={"cookies": []}, status="active")
        assert result["success"] is True
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("INSERT INTO browser_sessions" in s for s in sql_calls), f"Expected INSERT; got: {sql_calls}"
        assert any("ON CONFLICT" in s for s in sql_calls), "Expected upsert via ON CONFLICT"


class TestLoadSession:
    def test_returns_none_when_no_row(self, svc):
        with patch(
            "services.browser_session_service.get_db_cursor",
            return_value=_mock_cursor(row=None),
        ):
            result = svc.load_session(agent_id=7, platform="linkedin")
        assert result is None

    def test_returns_decrypted_state_when_active(self, svc):
        original = {"cookies": [{"name": "li_at", "value": "v"}]}
        ciphertext = svc.encrypt_state(original)
        row = {
            "id": 1,
            "agent_id": 7,
            "platform": "linkedin",
            "status": "active",
            "encrypted_state": ciphertext,
        }
        cm = _mock_cursor(row=row)
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            result = svc.load_session(agent_id=7, platform="linkedin")
        assert result == original
        # Verify last_used_at was bumped
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("UPDATE browser_sessions" in s and "last_used_at" in s for s in sql_calls)

    def test_returns_none_when_status_not_active(self, svc):
        original = {"cookies": []}
        row = {
            "id": 1,
            "agent_id": 7,
            "platform": "linkedin",
            "status": "stale",
            "encrypted_state": svc.encrypt_state(original),
        }
        with patch(
            "services.browser_session_service.get_db_cursor",
            return_value=_mock_cursor(row=row),
        ):
            result = svc.load_session(agent_id=7, platform="linkedin")
        assert result is None  # stale sessions are NOT loaded for skill execution


class TestStatusTransitions:
    def test_mark_stale_updates_status_and_reason(self, svc):
        cm = _mock_cursor(row={"id": 1})
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            svc.mark_stale(agent_id=7, platform="linkedin", reason="Page isn't available")
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("status" in s and "stale" in s for s in sql_calls)

    def test_mark_active_clears_failure_reason(self, svc):
        cm = _mock_cursor(row={"id": 1})
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            svc.mark_active(agent_id=7, platform="linkedin")
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("status" in s and "active" in s for s in sql_calls)
        assert any("last_failure_reason = NULL" in s for s in sql_calls)
