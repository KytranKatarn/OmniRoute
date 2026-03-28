"""Tests for subscription and add-on Stripe Checkout sessions."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_price_env(monkeypatch):
    """Set Stripe price env vars for all tests."""
    monkeypatch.setenv("KBS_STRIPE_PRICE_BUSINESS", "price_business_test")
    monkeypatch.setenv("KBS_STRIPE_PRICE_ENTERPRISE", "price_enterprise_test")
    monkeypatch.setenv(
        "KBS_STRIPE_ADDON_PRICES",
        json.dumps({"salon": "price_salon_test", "electrical": "price_elec_test"}),
    )


def _mock_session(url="https://checkout.stripe.com/test", sid="cs_test_123"):
    s = MagicMock()
    s.url = url
    s.id = sid
    return s


class TestSubscriptionCheckout:
    def test_business_tier_creates_subscription(self):
        # Reload module to pick up env vars
        import importlib
        import core.stripe_checkout as sc
        sc._TIER_PRICE_MAP["business"] = "price_business_test"
        sc._TIER_PRICE_MAP["enterprise"] = "price_enterprise_test"

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms, \
             patch("core.stripe_checkout._save_subscription_checkout"):
            ms.checkout.Session.create.return_value = mock_s
            result = sc.create_subscription_checkout(
                tenant_id=1, tier="business", customer_email="a@b.com"
            )

        assert result["url"] == mock_s.url
        assert result["session_id"] == mock_s.id
        kw = ms.checkout.Session.create.call_args[1]
        assert kw["mode"] == "subscription"
        assert kw["line_items"] == [{"price": "price_business_test", "quantity": 1}]
        assert kw["subscription_data"]["trial_period_days"] == 14
        assert kw["metadata"]["tier"] == "business"

    def test_enterprise_tier_no_trial(self):
        import core.stripe_checkout as sc
        sc._TIER_PRICE_MAP["enterprise"] = "price_enterprise_test"

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms, \
             patch("core.stripe_checkout._save_subscription_checkout"):
            ms.checkout.Session.create.return_value = mock_s
            sc.create_subscription_checkout(
                tenant_id=2, tier="enterprise", customer_email="c@d.com"
            )

        kw = ms.checkout.Session.create.call_args[1]
        assert "trial_period_days" not in kw["subscription_data"]

    def test_custom_trial_days(self):
        import core.stripe_checkout as sc
        sc._TIER_PRICE_MAP["business"] = "price_business_test"

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms, \
             patch("core.stripe_checkout._save_subscription_checkout"):
            ms.checkout.Session.create.return_value = mock_s
            sc.create_subscription_checkout(
                tenant_id=1,
                tier="business",
                customer_email="a@b.com",
                trial_days=30,
            )

        kw = ms.checkout.Session.create.call_args[1]
        assert kw["subscription_data"]["trial_period_days"] == 30

    def test_invalid_tier_raises(self):
        from core.stripe_checkout import create_subscription_checkout

        with pytest.raises(ValueError, match="No Stripe price ID"):
            create_subscription_checkout(
                tenant_id=1, tier="platinum", customer_email="x@y.com"
            )

    def test_free_tier_raises(self):
        from core.stripe_checkout import create_subscription_checkout

        with pytest.raises(ValueError, match="No Stripe price ID"):
            create_subscription_checkout(
                tenant_id=1, tier="free", customer_email="x@y.com"
            )

    def test_success_and_cancel_urls(self):
        import core.stripe_checkout as sc
        sc._TIER_PRICE_MAP["business"] = "price_business_test"

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms, \
             patch("core.stripe_checkout._save_subscription_checkout"):
            ms.checkout.Session.create.return_value = mock_s
            sc.create_subscription_checkout(
                tenant_id=1,
                tier="business",
                customer_email="a@b.com",
                success_url="https://example.com/ok",
                cancel_url="https://example.com/no",
            )

        kw = ms.checkout.Session.create.call_args[1]
        assert kw["success_url"] == "https://example.com/ok"
        assert kw["cancel_url"] == "https://example.com/no"


class TestAddonCheckout:
    def test_addon_creates_subscription(self):
        from core.stripe_checkout import create_addon_checkout

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms:
            ms.checkout.Session.create.return_value = mock_s
            result = create_addon_checkout(
                tenant_id=1, plugin_slug="salon", customer_email="a@b.com"
            )

        assert result["url"] == mock_s.url
        kw = ms.checkout.Session.create.call_args[1]
        assert kw["mode"] == "subscription"
        assert kw["line_items"] == [{"price": "price_salon_test", "quantity": 1}]
        assert kw["metadata"]["module_slug"] == "salon"
        assert kw["metadata"]["source"] == "kbs_addon"

    def test_unknown_addon_raises(self):
        from core.stripe_checkout import create_addon_checkout

        with pytest.raises(ValueError, match="No Stripe price ID"):
            create_addon_checkout(
                tenant_id=1, plugin_slug="nonexistent", customer_email="a@b.com"
            )
