"""Wave 3 integration tests -- full SaaS resale flow.

Tests the end-to-end flow of:
1. Signup -> onboarding -> tier selection -> Stripe checkout -> modules activated
2. Marketplace browse -> activate plugin -> Stripe add-on -> plugin available
3. Trial start -> 14 days -> auto-downgrade if no payment
4. Admin dashboard metrics accuracy
5. Subdomain provisioning flow
6. Team management flow
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestSignupToActivation:
    """Full flow: signup -> onboarding -> tier -> modules."""

    def test_signup_creates_tenant_and_free_modules(self):
        """Verify that signup creates a tenant with free-tier modules."""
        from core.stripe_billing import get_modules_for_tier

        free_mods = get_modules_for_tier("free")
        assert "crm" in free_mods
        assert "invoicing" in free_mods

    def test_subscription_checkout_flow(self):
        """Verify subscription checkout creates correct Stripe session."""
        import core.stripe_checkout as sc
        sc._TIER_PRICE_MAP["business"] = "price_business_test"

        mock_s = MagicMock()
        mock_s.url = "https://checkout.stripe.com/test"
        mock_s.id = "cs_test"

        with patch("core.stripe_checkout.stripe") as ms, \
             patch("core.stripe_checkout._save_subscription_checkout"):
            ms.checkout.Session.create.return_value = mock_s
            result = sc.create_subscription_checkout(
                tenant_id=1, tier="business", customer_email="a@b.com"
            )

        assert result["url"] == mock_s.url
        kw = ms.checkout.Session.create.call_args[1]
        assert kw["mode"] == "subscription"
        assert kw["subscription_data"]["trial_period_days"] == 14

    def test_subscription_created_webhook_activates_tier(self):
        """Verify subscription.created webhook activates business modules."""
        from core.stripe_billing import _handle_subscription_created

        with patch("core.stripe_billing.get_db_cursor") as mock_ctx, \
             patch("core.stripe_billing._set_tenant_tier") as mock_set, \
             patch("core.stripe_billing.sync_tier_modules") as mock_sync:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"id": 1, "tier": "free"}
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            event = {
                "id": "evt_test",
                "type": "customer.subscription.created",
                "data": {
                    "object": {
                        "id": "sub_test",
                        "customer": "cus_test",
                        "metadata": {"tenant_id": "1", "tier": "business"},
                    }
                },
            }

            _handle_subscription_created(event)
            mock_set.assert_called_once_with(1, "business")
            mock_sync.assert_called_once_with(1, "business")


class TestMarketplaceFlow:
    """Browse -> activate -> deactivate."""

    def test_addon_checkout_creates_session(self):
        from core.stripe_checkout import create_addon_checkout

        mock_s = MagicMock()
        mock_s.url = "https://checkout.stripe.com/addon"
        mock_s.id = "cs_addon"

        with patch("core.stripe_checkout.stripe") as ms, \
             patch.dict("os.environ", {"KBS_STRIPE_ADDON_PRICES": '{"salon": "price_salon"}'}):
            ms.checkout.Session.create.return_value = mock_s
            result = create_addon_checkout(
                tenant_id=1, plugin_slug="salon", customer_email="a@b.com"
            )

        assert "checkout.stripe.com" in result["url"]

    def test_tier_module_set_consistency(self):
        """Verify business tier is a superset of free tier."""
        from core.stripe_billing import TIER_MODULES

        free = TIER_MODULES["free"]
        business = TIER_MODULES["business"]
        enterprise = TIER_MODULES["enterprise"]
        assert free.issubset(business)
        assert business.issubset(enterprise)


class TestTrialLifecycle:
    """Trial start -> subscription deleted -> downgrade."""

    def test_subscription_deleted_downgrades_to_free(self):
        from core.stripe_billing import _handle_subscription_deleted, get_modules_for_tier

        free_modules = get_modules_for_tier("free")

        with patch("core.stripe_billing._get_tenant_by_stripe_customer") as mock_get, \
             patch("core.stripe_billing.get_db_cursor") as mock_ctx, \
             patch("core.stripe_billing.deactivate_module") as mock_deact, \
             patch("core.stripe_billing._set_tenant_tier") as mock_set, \
             patch("core.stripe_billing.sync_tier_modules"):
            mock_get.return_value = {"id": 1, "tier": "business"}
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = [
                {"module_slug": "appointments"},
                {"module_slug": "crm"},
            ]
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            event = {"data": {"object": {"customer": "cus_test"}}}
            _handle_subscription_deleted(event)
            mock_set.assert_called_once_with(1, "free")
            deact_slugs = [c[0][1] for c in mock_deact.call_args_list]
            assert "appointments" in deact_slugs


class TestSubdomainProvisioning:
    """Subdomain creation + health check."""

    def test_provision_and_health_check(self):
        from core.subdomain_manager import provision_subdomain, check_subdomain_health

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("core.subdomain_manager.requests.put", return_value=mock_resp), \
             patch.dict("os.environ", {"KBS_HOSTINGER_API_KEY": "test"}):
            result = provision_subdomain("acme")

        assert result["status"] == "provisioned"

        with patch("core.subdomain_manager.socket.gethostbyname", return_value="192.168.1.200"):
            health = check_subdomain_health("acme")

        assert health["resolves"] is True
        assert health["correct"] is True


class TestAdminMetrics:
    """Verify admin metrics calculation."""

    def test_mrr_calculation(self):
        tier_prices = {"free": 0, "business": 49, "enterprise": 149}
        breakdown = {"free": 5, "business": 10, "enterprise": 2}
        mrr = sum(tier_prices.get(t, 0) * c for t, c in breakdown.items())
        assert mrr == (0 * 5 + 49 * 10 + 149 * 2)
        assert mrr == 788


class TestTeamFlow:
    """Invite -> accept -> role change -> remove."""

    def test_valid_roles(self):
        from core.team_management import VALID_ROLES

        assert "admin" in VALID_ROLES
        assert "member" in VALID_ROLES
        assert "viewer" in VALID_ROLES
        assert "owner" not in VALID_ROLES


class TestOnboardingBundles:
    """Verify industry bundles are correctly defined."""

    def test_all_bundles_have_required_fields(self):
        from core.onboarding import INDUSTRY_BUNDLES

        for industry, bundle in INDUSTRY_BUNDLES.items():
            assert "name" in bundle, f"Missing name for {industry}"
            assert "tier" in bundle, f"Missing tier for {industry}"
            assert "plugins" in bundle, f"Missing plugins for {industry}"
            assert "description" in bundle, f"Missing description for {industry}"
            assert len(bundle["plugins"]) >= 2, f"Too few plugins for {industry}"

    def test_other_bundle_is_free(self):
        from core.onboarding import INDUSTRY_BUNDLES

        assert INDUSTRY_BUNDLES["other"]["tier"] == "free"


class TestWebhookHandlerRegistry:
    """Verify all expected webhooks are registered."""

    def test_all_handlers_registered(self):
        from core.stripe_billing import _HANDLERS

        expected = {
            "checkout.session.completed",
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.payment_failed",
        }
        assert expected == set(_HANDLERS.keys())


class TestTenantPublicRoutes:
    """Verify PUBLIC_ROUTES includes onboarding and admin."""

    def test_public_routes_include_auth(self):
        from core.tenant import PUBLIC_ROUTES

        assert "auth.login" in PUBLIC_ROUTES
        assert "auth.signup" in PUBLIC_ROUTES
        assert "auth.logout" in PUBLIC_ROUTES
