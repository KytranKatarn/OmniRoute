"""Tests for inbound email parsing (core/inbound_email.py)."""

from core.inbound_email import parse_inbound_email


def test_parse_inbound_email_basic():
    """Plain email with bare address: sender_email, subject, body extracted."""
    raw = {
        "from": "alice@example.com",
        "subject": "Cannot login to my account",
        "body_plain": "Hi, I keep getting an error when I try to log in.",
    }
    result = parse_inbound_email(raw)

    assert result["sender_email"] == "alice@example.com"
    assert result["subject"] == "Cannot login to my account"
    assert "error" in result["body"]
    assert result["is_reply"] is False
    assert result["ticket_number"] is None


def test_parse_inbound_email_with_name():
    """'Name <email>' format: sender_name and sender_email both extracted."""
    raw = {
        "from": "Bob Jones <bob@example.com>",
        "subject": "Billing question",
        "body_plain": "I was charged twice this month.",
    }
    result = parse_inbound_email(raw)

    assert result["sender_name"] == "Bob Jones"
    assert result["sender_email"] == "bob@example.com"
    assert result["is_reply"] is False


def test_parse_inbound_email_strips_reply_prefix():
    """Re: HD-NNNN: subject line → is_reply=True, ticket_number extracted, prefixes stripped."""
    raw = {
        "from": "carol@example.com",
        "subject": "Re: HD-0042: Login page broken",
        "body_plain": "Still broken after your last reply.",
    }
    result = parse_inbound_email(raw)

    assert result["is_reply"] is True
    assert result["ticket_number"] == "HD-0042"
    assert "Login page broken" in result["subject"]
    assert "Re:" not in result["subject"]
    assert "HD-0042" not in result["subject"]
