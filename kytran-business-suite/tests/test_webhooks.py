"""Tests for webhook registration, dispatch, and HMAC signing."""

import hashlib
import hmac
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest


def _mock_db_ctx(fetchone_val=None, fetchall_val=None):
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_val
    mock_cur.fetchall.return_value = fetchall_val or []
    mock_conn = MagicMock()

    @contextmanager
    def ctx_mgr(*args, **kwargs):
        yield mock_conn, mock_cur

    return ctx_mgr, mock_cur


class TestWebhookRegistration:
    @patch("core.webhook_manager.get_db_cursor")
    def test_register_webhook(self, mock_db):
        from core.webhook_manager import register_webhook

        webhook_row = {
            "id": 1, "tenant_id": 1, "url": "https://example.com/webhook",
            "events": ["invoice.created", "invoice.paid"],
            "secret": "test_secret_token", "is_active": True,
            "created_at": "2026-01-01",
        }
        ctx, cur = _mock_db_ctx(fetchone_val=webhook_row)
        mock_db.side_effect = ctx

        webhook = register_webhook(
            tenant_id=1,
            url="https://example.com/webhook",
            events=["invoice.created", "invoice.paid"],
        )
        assert webhook["id"] == 1
        assert webhook["url"] == "https://example.com/webhook"
        assert "invoice.created" in webhook["events"]

    @patch("core.webhook_manager.get_db_cursor")
    def test_list_webhooks(self, mock_db):
        from core.webhook_manager import list_webhooks

        hooks = [
            {"id": 1, "url": "https://example.com/hook", "events": ["*"],
             "is_active": True, "created_at": "2026-01-01"},
        ]
        ctx, cur = _mock_db_ctx(fetchall_val=hooks)
        mock_db.side_effect = ctx

        result = list_webhooks(tenant_id=1)
        assert len(result) == 1

    @patch("core.webhook_manager.get_db_cursor")
    def test_delete_webhook(self, mock_db):
        from core.webhook_manager import delete_webhook

        ctx, cur = _mock_db_ctx()
        mock_db.side_effect = ctx
        cur.fetchone.return_value = (1,)

        result = delete_webhook(webhook_id=1, tenant_id=1)
        assert result is True

    @patch("core.webhook_manager.get_db_cursor")
    def test_delete_nonexistent_webhook(self, mock_db):
        from core.webhook_manager import delete_webhook

        ctx, cur = _mock_db_ctx(fetchone_val=None)
        mock_db.side_effect = ctx

        result = delete_webhook(webhook_id=999, tenant_id=1)
        assert result is False


class TestWebhookDispatch:
    @patch("core.webhook_manager.requests.post")
    @patch("core.webhook_manager.get_db_cursor")
    def test_dispatch_to_matching_webhook(self, mock_db, mock_post):
        from core.webhook_manager import dispatch_webhooks

        webhooks = [
            {"id": 1, "url": "https://example.com/hook", "events": ["order.created"],
             "secret": "test_secret"},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        ctx, cur = _mock_db_ctx(fetchall_val=webhooks)
        mock_db.side_effect = ctx

        dispatch_webhooks(tenant_id=1, event_type="order.created", payload={"order_id": 42})

        # Give background thread a moment
        import time
        time.sleep(0.3)

        assert mock_post.called

    @patch("core.webhook_manager.requests.post")
    @patch("core.webhook_manager.get_db_cursor")
    def test_dispatch_wildcard_webhook(self, mock_db, mock_post):
        from core.webhook_manager import dispatch_webhooks

        webhooks = [
            {"id": 1, "url": "https://example.com/wildcard", "events": ["*"],
             "secret": "wild_secret"},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_post.return_value = mock_resp

        ctx, cur = _mock_db_ctx(fetchall_val=webhooks)
        mock_db.side_effect = ctx

        dispatch_webhooks(tenant_id=1, event_type="any.event", payload={"key": "val"})

        import time
        time.sleep(0.3)

        assert mock_post.called

    @patch("core.webhook_manager.get_db_cursor")
    def test_dispatch_no_matching_webhook(self, mock_db):
        from core.webhook_manager import dispatch_webhooks

        webhooks = [
            {"id": 1, "url": "https://example.com/hook", "events": ["invoice.paid"],
             "secret": "secret"},
        ]
        ctx, cur = _mock_db_ctx(fetchall_val=webhooks)
        mock_db.side_effect = ctx

        # This event doesn't match
        dispatch_webhooks(tenant_id=1, event_type="order.created", payload={"order_id": 1})
        # No thread should be started, no error


class TestHMACSignature:
    def test_compute_signature(self):
        from core.webhook_manager import _compute_signature

        payload = '{"event": "test", "data": {}}'
        secret = "my_secret"
        sig = _compute_signature(payload, secret)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        assert sig == expected

    def test_signature_changes_with_different_payload(self):
        from core.webhook_manager import _compute_signature

        sig1 = _compute_signature('{"a": 1}', "secret")
        sig2 = _compute_signature('{"a": 2}', "secret")
        assert sig1 != sig2

    def test_signature_changes_with_different_secret(self):
        from core.webhook_manager import _compute_signature

        sig1 = _compute_signature('{"a": 1}', "secret1")
        sig2 = _compute_signature('{"a": 1}', "secret2")
        assert sig1 != sig2


class TestEventBusWebhookIntegration:
    @patch("core.webhook_manager.dispatch_webhooks")
    def test_emit_triggers_webhook_dispatch(self, mock_dispatch):
        from core.event_bus import EventBus

        bus = EventBus()
        bus.emit("test.event", {"key": "val"}, tenant_id=42)

        mock_dispatch.assert_called_once_with(
            tenant_id=42,
            event_type="test.event",
            payload={
                "key": "val",
                "_event_type": "test.event",
                "_tenant_id": 42,
            },
        )

    @patch("core.webhook_manager.dispatch_webhooks")
    def test_emit_without_tenant_skips_webhooks(self, mock_dispatch):
        from core.event_bus import EventBus

        bus = EventBus()
        bus.emit("test.event", {"key": "val"})

        mock_dispatch.assert_not_called()
