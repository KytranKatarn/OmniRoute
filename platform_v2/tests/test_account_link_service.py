"""Unit tests for services.account_link_service (Project #311 task #2589)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


def _mock_cursor(row=None, rows=None):
    """Return a context-manager mock that fetches ``row`` / ``rows``."""
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
    cm.cursor = cur  # expose for assertions
    return cm


@pytest.fixture
def svc():
    from services import account_link_service

    return account_link_service


class TestTokenPrimitives:
    def test_generate_token_returns_url_safe_string(self, svc):
        tok = svc.generate_token()
        # URL-safe base64 of TOKEN_BYTES → ~43 chars (no padding)
        assert isinstance(tok, str)
        assert len(tok) >= 40
        # No '+' or '/' (must be URL-safe)
        assert "+" not in tok and "/" not in tok

    def test_generate_token_returns_unique_values(self, svc):
        toks = {svc.generate_token() for _ in range(20)}
        assert len(toks) == 20

    def test_hash_token_is_deterministic(self, svc):
        tok = "fixed-known-value"
        assert svc.hash_token(tok) == svc.hash_token(tok)
        assert svc.hash_token(tok) == hashlib.sha256(tok.encode()).hexdigest()

    def test_hash_token_differs_for_different_inputs(self, svc):
        assert svc.hash_token("a") != svc.hash_token("b")

    def test_constants(self, svc):
        assert svc.MAX_ALTERNATES_PER_USER == 5
        assert svc.VERIFICATION_TOKEN_TTL_HOURS == 24
        assert svc.TOKEN_BYTES == 32


class TestRequestAlternateEmail:
    """request_alternate_email(user_id, email) stages a verification."""

    def _user_row(self, **overrides):
        base = {
            "id": 7,
            "username": "kytrankatarn",
            "email": "kytran@kytranempowerment.com",
            "alternate_emails": [],
        }
        base.update(overrides)
        return base

    def test_happy_path_stages_verification(self, svc):
        user = self._user_row()
        cm = _mock_cursor(row=user)
        with patch("services.account_link_service.get_db_cursor", return_value=cm), patch(
            "services.account_link_service._send_verification_email"
        ) as send:
            result = svc.request_alternate_email(user_id=7, email="alt@gmail.com")
        assert result["success"] is True
        assert result["pending_email"] == "alt@gmail.com"
        assert "expires_at" in result
        send.assert_called_once()
        # Verify the INSERT actually fired against the staging table
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any(
            "INSERT INTO alternate_email_verifications" in s for s in sql_calls
        ), f"Expected INSERT into staging table; got SQL: {sql_calls}"

    def test_rejects_when_email_equals_primary(self, svc):
        user = self._user_row(email="me@x.com")
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=user)):
            result = svc.request_alternate_email(user_id=7, email="ME@X.COM")
        assert result["success"] is False
        assert "primary" in result["error"].lower()

    def test_rejects_when_already_verified(self, svc):
        user = self._user_row(alternate_emails=["alt@gmail.com"])
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=user)):
            result = svc.request_alternate_email(user_id=7, email="ALT@gmail.com")
        assert result["success"] is False
        assert "already" in result["error"].lower()

    def test_rejects_when_at_cap(self, svc):
        user = self._user_row(alternate_emails=[f"a{i}@x.com" for i in range(5)])
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=user)):
            result = svc.request_alternate_email(user_id=7, email="new@x.com")
        assert result["success"] is False
        assert "5" in result["error"] or "max" in result["error"].lower()

    def test_rejects_invalid_email_format(self, svc):
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=self._user_row())):
            result = svc.request_alternate_email(user_id=7, email="not-an-email")
        assert result["success"] is False
        assert "invalid" in result["error"].lower() or "format" in result["error"].lower()


class TestVerifyAlternateEmail:
    def _staging_row(self, **overrides):
        base = {
            "id": 1,
            "user_id": 7,
            "alternate_email": "alt@gmail.com",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "used_at": None,
        }
        base.update(overrides)
        return base

    def test_happy_path_appends_to_array_and_marks_used(self, svc):
        cm = _mock_cursor(row=self._staging_row())
        with patch("services.account_link_service.get_db_cursor", return_value=cm):
            result = svc.verify_alternate_email("anytoken")
        assert result["success"] is True
        assert result["alternate_email"] == "alt@gmail.com"
        assert result["user_id"] == 7
        # Confirm both the array UPDATE and the staging mark-used UPDATE fired
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any(
            "UPDATE users" in s and "alternate_emails" in s for s in sql_calls
        ), f"Expected UPDATE users alternate_emails; got: {sql_calls}"
        assert any(
            "UPDATE alternate_email_verifications" in s and "used_at" in s for s in sql_calls
        ), f"Expected UPDATE staging used_at; got: {sql_calls}"

    def test_returns_false_on_unknown_token(self, svc):
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=None)):
            result = svc.verify_alternate_email("badtoken")
        assert result["success"] is False
        assert "invalid" in result["error"].lower() or "not found" in result["error"].lower()

    def test_returns_false_on_expired_token(self, svc):
        row = self._staging_row(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=row)):
            result = svc.verify_alternate_email("expired")
        assert result["success"] is False
        assert "expired" in result["error"].lower()

    def test_returns_false_on_already_used_token(self, svc):
        row = self._staging_row(used_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=row)):
            result = svc.verify_alternate_email("used")
        assert result["success"] is False
        assert "used" in result["error"].lower()

    def test_returns_false_on_empty_token(self, svc):
        result = svc.verify_alternate_email("")
        assert result["success"] is False


class TestFindUserByAnyEmail:
    def test_matches_primary_case_insensitive(self, svc):
        with patch(
            "services.account_link_service.get_db_cursor", return_value=_mock_cursor(row={"id": 7, "email": "Me@X.COM"})
        ):
            user = svc.find_user_by_any_email("me@x.com")
        assert user is not None
        assert user["id"] == 7

    def test_matches_alternate_case_insensitive(self, svc):
        with patch(
            "services.account_link_service.get_db_cursor",
            return_value=_mock_cursor(row={"id": 7, "email": "primary@x.com"}),
        ):
            user = svc.find_user_by_any_email("ALT@gmail.com")
        assert user is not None
        assert user["id"] == 7

    def test_returns_none_when_no_match(self, svc):
        with patch("services.account_link_service.get_db_cursor", return_value=_mock_cursor(row=None)):
            user = svc.find_user_by_any_email("nobody@x.com")
        assert user is None

    def test_returns_none_on_empty_email(self, svc):
        # Should not even hit DB
        with patch("services.account_link_service.get_db_cursor") as cm:
            user = svc.find_user_by_any_email("")
        assert user is None
        cm.assert_not_called()

    def test_active_only_filter_includes_is_active_clause(self, svc):
        cm = _mock_cursor(row=None)
        with patch("services.account_link_service.get_db_cursor", return_value=cm):
            svc.find_user_by_any_email("me@x.com", active_only=True)
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("is_active" in s for s in sql_calls), f"Expected is_active filter; got: {sql_calls}"


class TestRemoveAlternateEmail:
    def test_removes_from_array_and_cancels_pending(self, svc):
        cm = _mock_cursor(row={"id": 7})
        with patch("services.account_link_service.get_db_cursor", return_value=cm):
            result = svc.remove_alternate_email(user_id=7, email="alt@gmail.com")
        assert result["success"] is True
        assert result["removed"] is True
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("array_remove" in s for s in sql_calls), f"Expected array_remove call; got: {sql_calls}"
        assert any(
            "UPDATE alternate_email_verifications" in s and "used_at" in s for s in sql_calls
        ), f"Expected pending-cancel UPDATE; got: {sql_calls}"

    def test_returns_removed_false_when_email_not_in_array(self, svc):
        cm = _mock_cursor(row=None)  # RETURNING returns None when WHERE doesn't match
        with patch("services.account_link_service.get_db_cursor", return_value=cm):
            result = svc.remove_alternate_email(user_id=7, email="missing@x.com")
        assert result["success"] is True
        assert result["removed"] is False

    def test_rejects_empty_email(self, svc):
        result = svc.remove_alternate_email(user_id=7, email="")
        assert result["success"] is False
        assert "email" in result["error"].lower()


class TestSendVerificationEmail:
    def test_email_send_failure_does_not_raise(self, svc, monkeypatch):
        """If Stalwart is down, the send must log and continue — never raise."""
        monkeypatch.setenv("SMTP_USER", "u")
        monkeypatch.setenv("SMTP_PASSWORD", "p")
        with patch(
            "services.account_link_service.smtplib.SMTP",
            side_effect=Exception("SMTP down"),
        ), patch("services.account_link_service.logger.exception") as log_exc:
            svc._send_verification_email("user@example.com", "user", "abc123")
        assert log_exc.called

    def test_missing_smtp_credentials_logs_error_and_returns(self, svc, monkeypatch):
        """Missing SMTP_USER / SMTP_PASSWORD must not attempt SMTP."""
        monkeypatch.setenv("SMTP_USER", "")
        monkeypatch.setenv("SMTP_PASSWORD", "")
        with patch("services.account_link_service.smtplib.SMTP") as smtp_cls, patch(
            "services.account_link_service.logger.error"
        ) as log_err:
            svc._send_verification_email("user@example.com", "user", "abc123")
        log_err.assert_called_once()
        smtp_cls.assert_not_called()

    def test_email_body_contains_verify_url_with_token(self, svc, monkeypatch):
        """Verify URL is constructed correctly and token appears in the message body."""
        import email as email_lib

        monkeypatch.setenv("SMTP_USER", "u")
        monkeypatch.setenv("SMTP_PASSWORD", "p")
        sendmail_calls = []
        with patch("services.account_link_service.smtplib.SMTP") as smtp_cls:
            smtp_inst = smtp_cls.return_value.__enter__.return_value
            smtp_inst.sendmail.side_effect = lambda *a, **kw: sendmail_calls.append(a)
            svc._send_verification_email("user@example.com", "user", "TOKEN-abc-123")
        assert sendmail_calls, "Expected sendmail to be called"
        raw_message = sendmail_calls[0][2]  # third positional arg is the raw message string
        # MIMEText with utf-8 charset base64-encodes the body — parse and decode it
        parsed = email_lib.message_from_string(raw_message)
        payload = parsed.get_payload(decode=True)
        body = payload.decode("utf-8") if payload else raw_message
        assert "TOKEN-abc-123" in body, f"Token not found in decoded body: {body[:200]}"
        assert "verify-alternate" in body
