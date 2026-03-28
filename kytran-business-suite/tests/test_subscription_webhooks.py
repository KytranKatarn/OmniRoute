"""Tests for subscription lifecycle webhook handlers."""

import json
from unittest.mock import patch, MagicMock

import pytest


def _make_event(event_type, obj, event_id="evt_test_001"):
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": obj},
    }


@pytest.fixture(autouse=True)
def _mock_db():
    """Mock all DB operations for webhook tests."""
    with patch("core.stripe_billing.get_db_cursor") as mock_ctx:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_cur


class TestSubscriptionCreated:
    def test_tier_subscription_activates_modules(self, _mock_db):
        from core.stripe_billing import _handle_subscription_created

        _mock_db.fetchone.return_value = {"id": 1, "tier": "free"}

        event = _make_event(
            "customer.subscription.created",
            {
                "id": "sub_test_001",
                "customer": "cus_test_001",
                "metadata": {"tenant_id": "1", "tier": "business"},
            },
        )

        with patch("core.stripe_billing._set_tenant_tier") as mock_set, \
             patch("core.stripe_billing.sync_tier_modules") as mock_sync:
            _handle_subscription_created(event)
            mock_set.assert_called_once_with(1, "business")
            mock_sync.assert_called_once_with(1, "business")

    def test_addon_subscription_activates_module(self, _mock_db):
        from core.stripe_billing import _handle_subscription_created

        _mock_db.fetchone.return_value = {"id": 1, "tier": "business"}

        event = _make_event(
            "customer.subscription.created",
            {
                "id": "sub_test_002",
                "customer": "cus_test_001",
                "metadata": {"tenant_id": "1", "module_slug": "salon"},
            },
        )

        with patch("core.stripe_billing.activate_module") as mock_act:
            _handle_subscription_created(event)
            mock_act.assert_called_once_with(1, "salon", source="addon_purchase")

    def test_no_tenant_logs_warning(self, _mock_db):
        from core.stripe_billing import _handle_subscription_created

        _mock_db.fetchone.return_value = None

        event = _make_event(
            "customer.subscription.created",
            {
                "id": "sub_test_003",
                "customer": "cus_unknown",
                "metadata": {},
            },
        )

        with patch("core.stripe_billing._get_tenant_by_stripe_customer", return_value=None):
            # Should not raise
            _handle_subscription_created(event)

    def test_trial_records_trial_end(self, _mock_db):
        from core.stripe_billing import _handle_subscription_created

        _mock_db.fetchone.return_value = {"id": 1, "tier": "free"}

        event = _make_event(
            "customer.subscription.created",
            {
                "id": "sub_test_004",
                "customer": "cus_test_001",
                "trial_end": 1743379200,
                "metadata": {"tenant_id": "1", "tier": "business"},
            },
        )

        with patch("core.stripe_billing._set_tenant_tier"), \
             patch("core.stripe_billing.sync_tier_modules"):
            _handle_subscription_created(event)
        calls = [str(c) for c in _mock_db.execute.call_args_list]
        assert any("trial_ends_at" in c for c in calls)


class TestSubscriptionDeleted:
    def test_downgrade_to_free(self, _mock_db):
        from core.stripe_billing import _handle_subscription_deleted

        _mock_db.fetchone.side_effect = [
            {"id": 1, "tier": "business"},
        ]
        _mock_db.fetchall.return_value = [
            {"module_slug": "appointments"},
            {"module_slug": "website-builder"},
            {"module_slug": "crm"},
        ]

        event = _make_event(
            "customer.subscription.deleted",
            {"customer": "cus_test_001"},
        )

        with patch("core.stripe_billing.deactivate_module") as mock_deact, \
             patch("core.stripe_billing._set_tenant_tier") as mock_set, \
             patch("core.stripe_billing.sync_tier_modules") as mock_sync, \
             patch("core.stripe_billing._get_tenant_by_stripe_customer", return_value={"id": 1, "tier": "business"}):
            _handle_subscription_deleted(event)
            mock_set.assert_called_once_with(1, "free")
            mock_sync.assert_called_once_with(1, "free")
            deact_slugs = [c[0][1] for c in mock_deact.call_args_list]
            assert "appointments" in deact_slugs
            assert "website-builder" in deact_slugs


class TestInvoicePaymentFailed:
    def test_first_failure_sets_grace_period(self, _mock_db):
        from core.stripe_billing import _handle_invoice_payment_failed

        event = _make_event(
            "invoice.payment_failed",
            {"customer": "cus_test_001", "attempt_count": 1},
        )

        with patch("core.stripe_billing._get_tenant_by_stripe_customer") as mock_get:
            mock_get.return_value = {"id": 1, "tier": "business"}
            _handle_invoice_payment_failed(event)
        calls = [str(c) for c in _mock_db.execute.call_args_list]
        assert any("payment_failed" in c for c in calls)

    def test_no_tenant_does_not_raise(self, _mock_db):
        from core.stripe_billing import _handle_invoice_payment_failed

        event = _make_event(
            "invoice.payment_failed",
            {"customer": "cus_unknown", "attempt_count": 1},
        )

        with patch("core.stripe_billing._get_tenant_by_stripe_customer") as mock_get:
            mock_get.return_value = None
            _handle_invoice_payment_failed(event)


class TestWebhookDispatch:
    def test_subscription_created_dispatched(self, _mock_db):
        from core.stripe_billing import _HANDLERS

        assert "customer.subscription.created" in _HANDLERS

    def test_invoice_payment_failed_dispatched(self, _mock_db):
        from core.stripe_billing import _HANDLERS

        assert "invoice.payment_failed" in _HANDLERS
