"""Unified email sending with multiple provider support."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core.config import Config

logger = logging.getLogger(__name__)


def send_email(to, subject, body, html_body=None, provider=None, from_addr=None):
    """Send an email via the configured provider.

    Args:
        to: Recipient address (string or list of strings).
        subject: Email subject line.
        body: Plain-text body.
        html_body: Optional HTML body. If provided, sends multipart/alternative.
        provider: Override provider (smtp, google, microsoft). Defaults to config.
        from_addr: Override sender address. Defaults to KBS_MAIL_FROM.

    Returns:
        True on success.

    Raises:
        ValueError: If provider is unknown.
        Exception: If sending fails.
    """
    cfg = Config()

    resolved_provider = provider or cfg.KBS_MAIL_PROVIDER
    resolved_from = from_addr or cfg.KBS_MAIL_FROM

    if resolved_provider == "smtp":
        _send_smtp(to, subject, body, html_body, resolved_from, cfg)
    elif resolved_provider == "google":
        _send_google(to, subject, body, html_body, resolved_from, cfg)
    elif resolved_provider == "microsoft":
        _send_microsoft(to, subject, body, html_body, resolved_from, cfg)
    else:
        raise ValueError(f"Unknown mail provider: {resolved_provider}")

    return True


def _send_smtp(to, subject, body, html_body, from_addr, cfg):
    """Send email via SMTP with STARTTLS (Stalwart, SendGrid, Mailgun, etc.)."""
    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(cfg.KBS_SMTP_HOST, cfg.KBS_SMTP_PORT) as server:
        server.starttls()
        if cfg.KBS_SMTP_USER and cfg.KBS_SMTP_PASSWORD:
            server.login(cfg.KBS_SMTP_USER, cfg.KBS_SMTP_PASSWORD)
        server.sendmail(from_addr, recipients, msg.as_string())

    logger.info("Email sent via SMTP to %s", recipients)


def _send_google(to, subject, body, html_body, from_addr, cfg):
    """Send via Gmail API (stub — falls back to SMTP until full implementation)."""
    logger.warning(
        "Google Gmail API provider not yet implemented — falling back to SMTP"
    )
    _send_smtp(to, subject, body, html_body, from_addr, cfg)


def _send_microsoft(to, subject, body, html_body, from_addr, cfg):
    """Send via Microsoft Graph API (stub — falls back to SMTP until full implementation)."""
    logger.warning(
        "Microsoft Graph API provider not yet implemented — falling back to SMTP"
    )
    _send_smtp(to, subject, body, html_body, from_addr, cfg)
