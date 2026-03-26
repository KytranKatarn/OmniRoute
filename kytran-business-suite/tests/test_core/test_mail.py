"""Tests for core/mail_client.py — unified email sending."""

import pytest
from unittest.mock import patch, MagicMock

from core.mail_client import send_email


@pytest.fixture(autouse=True)
def mail_env(monkeypatch):
    """Set baseline mail env vars for all tests."""
    monkeypatch.setenv("KBS_MAIL_PROVIDER", "smtp")
    monkeypatch.setenv("KBS_SMTP_HOST", "mail.test.com")
    monkeypatch.setenv("KBS_SMTP_PORT", "587")
    monkeypatch.setenv("KBS_SMTP_USER", "user@test.com")
    monkeypatch.setenv("KBS_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("KBS_MAIL_FROM", "noreply@test.com")


class TestSMTPProvider:
    def test_smtp_sends_email(self):
        """SMTP provider calls smtplib.SMTP and sends the message."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email(
                to="recipient@example.com",
                subject="Hello",
                body="Test body",
            )

        assert result is True
        mock_smtp_cls.assert_called_once_with("mail.test.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@test.com", "secret")
        mock_server.sendmail.assert_called_once()

    def test_smtp_sends_with_html_body(self):
        """SMTP provider attaches HTML part when html_body is provided."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email(
                to="recipient@example.com",
                subject="Hello HTML",
                body="Plain text",
                html_body="<p>HTML content</p>",
            )

        assert result is True
        mock_server.sendmail.assert_called_once()
        # Verify the message string contains both parts
        call_args = mock_server.sendmail.call_args
        msg_string = call_args[0][2]
        assert "Plain text" in msg_string
        assert "HTML content" in msg_string

    def test_smtp_accepts_list_of_recipients(self):
        """SMTP provider handles list of recipient addresses."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email(
                to=["a@test.com", "b@test.com"],
                subject="Multi",
                body="Body",
            )

        assert result is True
        call_args = mock_server.sendmail.call_args
        recipients = call_args[0][1]
        assert recipients == ["a@test.com", "b@test.com"]


class TestUnknownProvider:
    def test_unknown_provider_raises_value_error(self, monkeypatch):
        """Unknown provider string raises ValueError with provider name."""
        monkeypatch.setenv("KBS_MAIL_PROVIDER", "carrier_pigeon")

        with pytest.raises(ValueError, match="Unknown mail provider: carrier_pigeon"):
            send_email(to="x@test.com", subject="Hi", body="Body")

    def test_explicit_unknown_provider_raises(self):
        """Explicit provider override with unknown value raises ValueError."""
        with pytest.raises(ValueError, match="Unknown mail provider: fax"):
            send_email(
                to="x@test.com",
                subject="Hi",
                body="Body",
                provider="fax",
            )


class TestGoogleProvider:
    def test_google_falls_back_to_smtp(self, monkeypatch):
        """Google provider logs warning and delegates to SMTP."""
        monkeypatch.setenv("KBS_MAIL_PROVIDER", "google")

        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.mail_client.logger") as mock_logger:
                result = send_email(
                    to="recipient@example.com",
                    subject="Google test",
                    body="Body",
                )

        assert result is True
        mock_smtp_cls.assert_called_once()
        mock_server.sendmail.assert_called_once()
        mock_logger.warning.assert_called_once()
        assert "Google" in mock_logger.warning.call_args[0][0]

    def test_google_explicit_provider_falls_back_to_smtp(self):
        """Explicit google provider override falls back to SMTP."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email(
                to="recipient@example.com",
                subject="Test",
                body="Body",
                provider="google",
            )

        assert result is True
        mock_smtp_cls.assert_called_once()


class TestMicrosoftProvider:
    def test_microsoft_falls_back_to_smtp(self, monkeypatch):
        """Microsoft provider logs warning and delegates to SMTP."""
        monkeypatch.setenv("KBS_MAIL_PROVIDER", "microsoft")

        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.mail_client.logger") as mock_logger:
                result = send_email(
                    to="recipient@example.com",
                    subject="MS test",
                    body="Body",
                )

        assert result is True
        mock_smtp_cls.assert_called_once()
        mock_server.sendmail.assert_called_once()
        mock_logger.warning.assert_called_once()
        assert "Microsoft" in mock_logger.warning.call_args[0][0]

    def test_microsoft_explicit_provider_falls_back_to_smtp(self):
        """Explicit microsoft provider override falls back to SMTP."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = send_email(
                to="recipient@example.com",
                subject="Test",
                body="Body",
                provider="microsoft",
            )

        assert result is True
        mock_smtp_cls.assert_called_once()


class TestDefaultFromAddress:
    def test_default_from_addr_uses_config(self):
        """When from_addr not passed, uses KBS_MAIL_FROM from config."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_email(to="recipient@example.com", subject="Test", body="Body")

        call_args = mock_server.sendmail.call_args
        from_used = call_args[0][0]
        assert from_used == "noreply@test.com"

    def test_explicit_from_addr_overrides_config(self):
        """Explicit from_addr overrides KBS_MAIL_FROM."""
        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_email(
                to="recipient@example.com",
                subject="Test",
                body="Body",
                from_addr="custom@sender.com",
            )

        call_args = mock_server.sendmail.call_args
        from_used = call_args[0][0]
        assert from_used == "custom@sender.com"

    def test_config_from_addr_uses_env_var(self, monkeypatch):
        """KBS_MAIL_FROM env var is used as default sender."""
        monkeypatch.setenv("KBS_MAIL_FROM", "alerts@kytranempowerment.com")

        with patch("core.mail_client.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_email(to="recipient@example.com", subject="Test", body="Body")

        call_args = mock_server.sendmail.call_args
        from_used = call_args[0][0]
        assert from_used == "alerts@kytranempowerment.com"
