from unittest.mock import patch, MagicMock


class TestStalwartService:
    def test_create_mailbox_accepts_quota_gb(self):
        with patch("tools.email_manager.stalwart_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            from tools.email_manager import stalwart_service

            stalwart_service.create_mailbox("kytran@kytranempowerment.com", quota_gb=10)
            assert mock_post.called
            call_json = mock_post.call_args[1]["json"]
            assert call_json.get("quota") == 10 * 1024 * 1024 * 1024

    def test_create_mailbox_default_quota_is_1gb(self):
        with patch("tools.email_manager.stalwart_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            from tools.email_manager import stalwart_service

            stalwart_service.create_mailbox("test@kytranempowerment.com")
            call_json = mock_post.call_args[1]["json"]
            assert call_json.get("quota") == 1 * 1024 * 1024 * 1024

    def test_create_mailbox_returns_ok_and_password(self):
        with patch("tools.email_manager.stalwart_service.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=201)
            from tools.email_manager import stalwart_service

            result = stalwart_service.create_mailbox("kytran@kytranempowerment.com")
            assert result["ok"] is True
            assert "password" in result


class TestEmailParser:
    def test_decode_header_value_plain(self):
        from tools.email_manager.email_parser import decode_header_value

        assert decode_header_value("Hello World") == "Hello World"

    def test_decode_header_value_encoded(self):
        from tools.email_manager.email_parser import decode_header_value

        encoded = "=?utf-8?b?SGVsbG8gV29ybGQ=?="
        assert decode_header_value(encoded) == "Hello World"

    def test_decode_header_value_empty(self):
        from tools.email_manager.email_parser import decode_header_value

        assert decode_header_value("") == ""

    def test_parse_received_at_valid_date(self):
        import email.message
        from tools.email_manager.email_parser import parse_received_at
        from datetime import timezone

        msg = email.message.Message()
        msg["Date"] = "Mon, 10 May 2026 12:00:00 +0000"
        dt = parse_received_at(msg)
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026

    def test_parse_received_at_fallback(self):
        import email.message
        from tools.email_manager.email_parser import parse_received_at

        msg = email.message.Message()
        dt = parse_received_at(msg)
        assert dt.year >= 2026

    def test_extract_body_parts_plain_text(self):
        import email.message
        from tools.email_manager.email_parser import extract_body_parts

        msg = email.message.Message()
        msg["Content-Type"] = "text/plain; charset=utf-8"
        msg.set_payload("Hello from Kytran", charset="utf-8")
        parts = extract_body_parts(msg)
        assert parts["text"] == "Hello from Kytran"
        assert parts["html"] is None
        assert parts["preview"] == "Hello from Kytran"
        assert parts["attachments"] == []

    def test_extract_body_parts_preview_truncated(self):
        import email.message
        from tools.email_manager.email_parser import extract_body_parts

        msg = email.message.Message()
        msg["Content-Type"] = "text/plain; charset=utf-8"
        long_text = "A" * 500
        msg.set_payload(long_text, charset="utf-8")
        parts = extract_body_parts(msg)
        assert len(parts["preview"]) == 200

    def test_extract_body_parts_strips_html_for_preview(self):
        import email.message
        from tools.email_manager.email_parser import extract_body_parts

        msg = email.message.Message()
        msg["Content-Type"] = "text/html; charset=utf-8"
        msg.set_payload("<p>Hello <b>World</b></p>", charset="utf-8")
        parts = extract_body_parts(msg)
        assert "<" not in parts["preview"]
        assert "Hello" in parts["preview"]
