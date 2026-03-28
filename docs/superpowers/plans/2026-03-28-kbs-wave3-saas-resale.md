# KBS Wave 3: SaaS Resale Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Self-serve client onboarding, billing, and marketplace. Clients sign up, pick a plan, pay via Stripe, and start using KBS without Kytran Empowerment touching anything. Includes subscription checkout, webhook lifecycle, marketplace UI, onboarding wizard, subdomain provisioning, client/admin dashboards, and team management.

**Architecture:** Extends existing `core/stripe_checkout.py` and `core/stripe_billing.py` with subscription flows. The marketplace blueprint (`core/marketplace.py`) is expanded into a full API + UI. A new `core/subdomain_manager.py` handles DNS provisioning via Hostinger API. Onboarding is a multi-step wizard stored in tenant `settings` JSONB. Admin metrics live behind an owner-only guard. Team management adds invite/role endpoints to the auth system. All tenant data stays in per-tenant schemas. Events flow through `event_bus.emit()`.

**Tech Stack:** Flask, PostgreSQL, psycopg2, stripe (already installed), requests, pytest

**Pricing (CAD):**
| Tier | Monthly | Trial |
|------|---------|-------|
| Free | $0 | -- |
| Business | $49 | 14-day |
| Enterprise | $149 | -- |
| Industry add-on | $29 each | -- |
| A la carte plugin | $9-19 each | -- |

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `core/stripe_checkout.py` | Add subscription + add-on checkout sessions |
| Modify | `core/stripe_billing.py` | Add subscription.created, invoice.payment_failed handlers; stripe_events table |
| Modify | `core/marketplace.py` | Full marketplace API: list, detail, activate, trial, deactivate |
| Modify | `core/config.py` | Add Stripe price IDs, Hostinger DNS, base domain env vars |
| Modify | `core/auth.py` | Wire subdomain provisioning on signup; onboarding redirect |
| Modify | `core/tenant.py` | Add PUBLIC_ROUTES for onboarding, admin |
| Modify | `core/app.py` | Register onboarding, admin, team, dashboard-stats routes |
| Create | `core/subdomain_manager.py` | Hostinger DNS CNAME provisioning + health check |
| Create | `core/onboarding.py` | Onboarding wizard routes + API |
| Create | `core/admin_dashboard.py` | Admin dashboard routes + metrics API |
| Create | `core/team_management.py` | Team invite, list, role, remove routes |
| Create | `core/dashboard_stats.py` | Dashboard stats aggregation API |
| Rewrite | `shared/templates/marketplace.html` | Full marketplace UI with cards, filters, modals |
| Create | `shared/templates/onboarding.html` | Multi-step onboarding wizard |
| Create | `shared/templates/admin_dashboard.html` | Admin metrics dashboard |
| Modify | `shared/templates/dashboard.html` | Enhanced client dashboard |
| Create | `migrations/003_wave3_saas_resale.sql` | stripe_events, team_invites, onboarding tables |
| Create | `tests/test_subscription_checkout.py` | Subscription + add-on checkout tests |
| Create | `tests/test_subscription_webhooks.py` | Subscription lifecycle webhook tests |
| Create | `tests/test_marketplace_api.py` | Marketplace API tests |
| Create | `tests/test_onboarding.py` | Onboarding wizard tests |
| Create | `tests/test_subdomain_manager.py` | DNS provisioning tests (mocked Hostinger) |
| Create | `tests/test_dashboard_stats.py` | Dashboard stats API tests |
| Create | `tests/test_admin_dashboard.py` | Admin metrics tests |
| Create | `tests/test_team_management.py` | Team CRUD tests |
| Create | `tests/test_wave3_integration.py` | Full SaaS resale flow integration tests |

---

## Task 1: Subscription Checkout Flow

**Files:**
- Modify: `core/stripe_checkout.py`
- Modify: `core/config.py`
- Create: `tests/test_subscription_checkout.py`

- [ ] **Step 1: Add Stripe price env vars to Config**

Edit `core/config.py` -- add after the existing Stripe block (after line 46):

```python
        # Stripe subscription price IDs (Stripe Dashboard -> Products -> Prices)
        self.KBS_STRIPE_PRICE_BUSINESS = os.getenv("KBS_STRIPE_PRICE_BUSINESS", "")
        self.KBS_STRIPE_PRICE_ENTERPRISE = os.getenv("KBS_STRIPE_PRICE_ENTERPRISE", "")
        # Add-on / a-la-carte price IDs stored as JSON: {"salon": "price_xxx", ...}
        self.KBS_STRIPE_ADDON_PRICES = os.getenv("KBS_STRIPE_ADDON_PRICES", "{}")

        # Hostinger DNS (subdomain provisioning)
        self.KBS_HOSTINGER_API_KEY = os.getenv("KBS_HOSTINGER_API_KEY", "")
        self.KBS_BASE_DOMAIN = os.getenv("KBS_BASE_DOMAIN", "kytranempowerment.com")
        self.KBS_SUBDOMAIN_TARGET = os.getenv(
            "KBS_SUBDOMAIN_TARGET", "192.168.1.200"
        )
```

- [ ] **Step 2: Add subscription checkout to stripe_checkout.py**

Append to `core/stripe_checkout.py`:

```python
# ---------------------------------------------------------------------------
# Subscription checkout
# ---------------------------------------------------------------------------

# Tier -> Stripe Price ID mapping (loaded from env)
_TIER_PRICE_MAP = {
    "business": os.getenv("KBS_STRIPE_PRICE_BUSINESS", ""),
    "enterprise": os.getenv("KBS_STRIPE_PRICE_ENTERPRISE", ""),
}


def create_subscription_checkout(
    tenant_id: int,
    tier: str,
    customer_email: str,
    success_url: str = None,
    cancel_url: str = None,
    trial_days: int = None,
) -> dict:
    """Create a Stripe Checkout Session for a subscription.

    Args:
        tenant_id: Tenant purchasing the subscription.
        tier: 'business' or 'enterprise'.
        customer_email: Email for the Stripe customer.
        success_url: Redirect on success.
        cancel_url: Redirect on cancel.
        trial_days: If set, adds a trial period (default 14 for business).

    Returns:
        Dict with 'url' (redirect URL) and 'session_id'.

    Raises:
        ValueError: If tier is invalid or has no price ID configured.
    """
    price_id = _TIER_PRICE_MAP.get(tier)
    if not price_id:
        raise ValueError(
            f"No Stripe price ID configured for tier '{tier}'. "
            f"Set KBS_STRIPE_PRICE_{tier.upper()} env var."
        )

    # Default trial: 14 days for business tier
    if trial_days is None and tier == "business":
        trial_days = 14

    checkout_params = {
        "mode": "subscription",
        "customer_email": customer_email,
        "line_items": [{"price": price_id, "quantity": 1}],
        "metadata": {
            "tenant_id": str(tenant_id),
            "tier": tier,
            "source": "kbs_subscription",
        },
        "subscription_data": {
            "metadata": {"tenant_id": str(tenant_id), "tier": tier},
        },
        "success_url": success_url or f"{_BASE_URL}/dashboard?subscription=success",
        "cancel_url": cancel_url or f"{_BASE_URL}/marketplace?subscription=cancelled",
    }

    if trial_days and trial_days > 0:
        checkout_params["subscription_data"]["trial_period_days"] = trial_days

    session = stripe.checkout.Session.create(**checkout_params)

    # Record the checkout attempt
    _save_subscription_checkout(tenant_id, session.id, tier)

    logger.info(
        "Created Stripe subscription checkout %s for tenant %s (tier=%s, trial=%s)",
        session.id,
        tenant_id,
        tier,
        trial_days,
    )

    return {"url": session.url, "session_id": session.id}


def create_addon_checkout(
    tenant_id: int,
    plugin_slug: str,
    customer_email: str,
    success_url: str = None,
    cancel_url: str = None,
) -> dict:
    """Create a Stripe Checkout Session for an add-on plugin subscription.

    Args:
        tenant_id: Tenant purchasing the add-on.
        plugin_slug: Plugin slug (e.g. 'salon', 'electrical').
        customer_email: Email for the Stripe customer.
        success_url: Redirect on success.
        cancel_url: Redirect on cancel.

    Returns:
        Dict with 'url' and 'session_id'.

    Raises:
        ValueError: If no price ID is configured for this plugin.
    """
    import json as _json

    addon_prices = _json.loads(os.getenv("KBS_STRIPE_ADDON_PRICES", "{}"))
    price_id = addon_prices.get(plugin_slug)

    if not price_id:
        raise ValueError(
            f"No Stripe price ID configured for add-on plugin '{plugin_slug}'. "
            f"Add it to KBS_STRIPE_ADDON_PRICES JSON env var."
        )

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=customer_email,
        line_items=[{"price": price_id, "quantity": 1}],
        metadata={
            "tenant_id": str(tenant_id),
            "module_slug": plugin_slug,
            "source": "kbs_addon",
        },
        subscription_data={
            "metadata": {
                "tenant_id": str(tenant_id),
                "module_slug": plugin_slug,
            },
        },
        success_url=success_url
        or f"{_BASE_URL}/marketplace?addon={plugin_slug}&status=success",
        cancel_url=cancel_url
        or f"{_BASE_URL}/marketplace?addon={plugin_slug}&status=cancelled",
    )

    logger.info(
        "Created Stripe addon checkout %s for tenant %s plugin %s",
        session.id,
        tenant_id,
        plugin_slug,
    )

    return {"url": session.url, "session_id": session.id}


def _save_subscription_checkout(
    tenant_id: int, session_id: str, tier: str
) -> None:
    """Record subscription checkout attempt in tenants metadata."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE tenants
                SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    f'{{"last_checkout_session": "{session_id}", "pending_tier": "{tier}"}}',
                    tenant_id,
                ),
            )
    except Exception:
        logger.exception(
            "Failed to save subscription checkout for tenant %s", tenant_id
        )
```

- [ ] **Step 3: Write subscription checkout tests**

Create `tests/test_subscription_checkout.py`:

```python
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
        from core.stripe_checkout import create_subscription_checkout

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms:
            ms.checkout.Session.create.return_value = mock_s
            result = create_subscription_checkout(
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
        from core.stripe_checkout import create_subscription_checkout

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms:
            ms.checkout.Session.create.return_value = mock_s
            result = create_subscription_checkout(
                tenant_id=2, tier="enterprise", customer_email="c@d.com"
            )

        kw = ms.checkout.Session.create.call_args[1]
        assert "trial_period_days" not in kw["subscription_data"]

    def test_custom_trial_days(self):
        from core.stripe_checkout import create_subscription_checkout

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms:
            ms.checkout.Session.create.return_value = mock_s
            create_subscription_checkout(
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
        from core.stripe_checkout import create_subscription_checkout

        mock_s = _mock_session()
        with patch("core.stripe_checkout.stripe") as ms:
            ms.checkout.Session.create.return_value = mock_s
            create_subscription_checkout(
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
```

- [ ] **Step 4: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_subscription_checkout.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/stripe_checkout.py core/config.py tests/test_subscription_checkout.py && git commit -m "feat(billing): subscription + add-on checkout flows with Stripe"
```

---

## Task 2: Subscription Webhook Handlers

**Files:**
- Modify: `core/stripe_billing.py`
- Create: `migrations/003_wave3_saas_resale.sql`
- Create: `tests/test_subscription_webhooks.py`

- [ ] **Step 1: Create the Wave 3 migration**

Create `migrations/003_wave3_saas_resale.sql`:

```sql
-- Wave 3: SaaS Resale Infrastructure tables
-- Run against the public schema (not tenant schemas).
-- All statements are idempotent.

-- ----------------------------------------------------------------
-- Stripe Events (already partially used -- ensure table exists)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stripe_events (
    id              SERIAL PRIMARY KEY,
    stripe_event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type      VARCHAR(100) NOT NULL,
    tenant_id       INTEGER REFERENCES tenants(id),
    payload         JSONB NOT NULL DEFAULT '{}',
    processed       BOOLEAN DEFAULT FALSE,
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stripe_events_type      ON stripe_events (event_type);
CREATE INDEX IF NOT EXISTS idx_stripe_events_tenant_id ON stripe_events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_stripe_events_processed ON stripe_events (processed);
CREATE INDEX IF NOT EXISTS idx_stripe_events_created   ON stripe_events (created_at);

-- ----------------------------------------------------------------
-- Team Invites
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_invites (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    email           VARCHAR(255) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'member'
                        CHECK (role IN ('admin', 'member', 'viewer')),
    invited_by      INTEGER NOT NULL REFERENCES users(id),
    token           VARCHAR(255) UNIQUE NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'expired', 'revoked')),
    created_at      TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP DEFAULT NOW() + INTERVAL '7 days',
    accepted_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_team_invites_tenant_id ON team_invites (tenant_id);
CREATE INDEX IF NOT EXISTS idx_team_invites_email     ON team_invites (email);
CREATE INDEX IF NOT EXISTS idx_team_invites_token     ON team_invites (token);
CREATE INDEX IF NOT EXISTS idx_team_invites_status    ON team_invites (status);

-- ----------------------------------------------------------------
-- Add onboarding + subscription fields to tenants
-- ----------------------------------------------------------------
-- settings JSONB already exists on tenants, used for:
--   onboarding_step, onboarding_complete, industry, timezone, logo_url,
--   stripe_subscription_id, pending_tier, last_checkout_session,
--   trial_ends_at, grace_period_ends_at

-- Add stripe_subscription_id column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenants' AND column_name = 'stripe_subscription_id'
    ) THEN
        ALTER TABLE tenants ADD COLUMN stripe_subscription_id VARCHAR(255);
    END IF;
END $$;

-- Add trial_ends_at column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenants' AND column_name = 'trial_ends_at'
    ) THEN
        ALTER TABLE tenants ADD COLUMN trial_ends_at TIMESTAMP;
    END IF;
END $$;

-- ----------------------------------------------------------------
-- Module catalog enhancements
-- ----------------------------------------------------------------
-- Add price_monthly column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'module_catalog' AND column_name = 'price_monthly'
    ) THEN
        ALTER TABLE module_catalog ADD COLUMN price_monthly DECIMAL(10,2);
    END IF;
END $$;

-- Add features JSONB column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'module_catalog' AND column_name = 'features'
    ) THEN
        ALTER TABLE module_catalog ADD COLUMN features JSONB DEFAULT '[]';
    END IF;
END $$;

-- ----------------------------------------------------------------
-- Add trial_ends_at to tenant_modules
-- ----------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tenant_modules' AND column_name = 'trial_ends_at'
    ) THEN
        ALTER TABLE tenant_modules ADD COLUMN trial_ends_at TIMESTAMP;
    END IF;
END $$;
```

- [ ] **Step 2: Add subscription.created and invoice.payment_failed handlers to stripe_billing.py**

Add these handler functions before the `_HANDLERS` dict in `core/stripe_billing.py`:

```python
def _handle_subscription_created(event: dict) -> None:
    """customer.subscription.created -- activate tier modules, record subscription ID."""
    subscription = event.get("data", {}).get("object", {})
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")
    metadata = subscription.get("metadata", {})
    tier = metadata.get("tier", "")
    module_slug = metadata.get("module_slug", "")
    tenant_id_str = metadata.get("tenant_id")

    # Try metadata first, then customer lookup
    tenant = None
    if tenant_id_str:
        with get_db_cursor(dict_cursor=True) as (conn, cur):
            cur.execute("SELECT id, tier FROM tenants WHERE id = %s", (int(tenant_id_str),))
            tenant = cur.fetchone()

    if not tenant and customer_id:
        tenant = _get_tenant_by_stripe_customer(customer_id)

    if not tenant:
        logger.warning(
            "subscription.created: no tenant found (customer=%s, metadata=%s)",
            customer_id,
            metadata,
        )
        return

    tid = tenant["id"]

    if module_slug:
        # Add-on subscription
        activate_module(tid, module_slug, source="addon_purchase")
        logger.info("Activated addon module %s for tenant %s via subscription", module_slug, tid)
    elif tier:
        # Tier subscription
        _set_tenant_tier(tid, tier)
        sync_tier_modules(tid, tier)

        # Store subscription ID and link Stripe customer
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE tenants
                SET stripe_subscription_id = %s,
                    stripe_customer_id = COALESCE(stripe_customer_id, %s),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (subscription_id, customer_id, tid),
            )

        # Check for trial
        trial_end = subscription.get("trial_end")
        if trial_end:
            from datetime import datetime

            trial_dt = datetime.utcfromtimestamp(trial_end)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE tenants SET trial_ends_at = %s WHERE id = %s",
                    (trial_dt, tid),
                )

        logger.info("Activated tier %s for tenant %s via subscription %s", tier, tid, subscription_id)


def _handle_invoice_payment_failed(event: dict) -> None:
    """invoice.payment_failed -- notify tenant, set grace period."""
    invoice_obj = event.get("data", {}).get("object", {})
    customer_id = invoice_obj.get("customer")
    attempt_count = invoice_obj.get("attempt_count", 0)

    tenant = _get_tenant_by_stripe_customer(customer_id) if customer_id else None
    if not tenant:
        logger.warning("invoice.payment_failed: no tenant for customer %s", customer_id)
        return

    tid = tenant["id"]

    # Set a 7-day grace period on first failure
    if attempt_count <= 1:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE tenants
                SET settings = COALESCE(settings, '{}'::jsonb)
                    || '{"payment_failed": true}'::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (tid,),
            )
        logger.warning(
            "Payment failed for tenant %s (attempt %s) -- 7-day grace period started",
            tid,
            attempt_count,
        )
    else:
        logger.warning(
            "Payment failed for tenant %s (attempt %s) -- grace period continues",
            tid,
            attempt_count,
        )
```

- [ ] **Step 3: Update the _HANDLERS dict to include new event types**

Replace the `_HANDLERS` dict in `core/stripe_billing.py`:

```python
_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.created": _handle_subscription_created,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_invoice_payment_failed,
}
```

- [ ] **Step 4: Write subscription webhook tests**

Create `tests/test_subscription_webhooks.py`:

```python
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
             patch("core.stripe_billing.sync_tier_modules") as mock_sync:
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
```

- [ ] **Step 5: Run migration and tests**

```bash
docker exec kbs_app python -c "from core.database import run_migration_file; run_migration_file('/app/migrations/003_wave3_saas_resale.sql')"
docker exec kbs_app python -m pytest tests/test_subscription_webhooks.py -v
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/stripe_billing.py migrations/003_wave3_saas_resale.sql tests/test_subscription_webhooks.py && git commit -m "feat(billing): subscription webhook handlers + Wave 3 migration"
```

---

## Task 3: Marketplace Database + API

**Files:**
- Modify: `core/marketplace.py`
- Create: `tests/test_marketplace_api.py`

- [ ] **Step 1: Rewrite core/marketplace.py with full API**

Replace `core/marketplace.py` entirely:

```python
"""
core/marketplace.py -- Plugin marketplace API and UI.

Provides browsing, activation, trial, and deactivation of plugins
for the current tenant.
"""

import json
import logging
import os
from datetime import datetime, timedelta

from flask import Blueprint, abort, g, jsonify, render_template, request, session
from flask_login import current_user, login_required

from core.database import get_db_cursor
from core.stripe_billing import activate_module, deactivate_module, get_modules_for_tier

logger = logging.getLogger(__name__)

marketplace_bp = Blueprint(
    "marketplace", __name__, template_folder="../shared/templates"
)


# ---------------------------------------------------------------------------
# UI route
# ---------------------------------------------------------------------------


@marketplace_bp.route("/")
@login_required
def index():
    """Render the marketplace page."""
    return render_template("marketplace.html")


# ---------------------------------------------------------------------------
# API: List all plugins
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins")
@login_required
def list_plugins():
    """Return all plugins from module_catalog with activation status for current tenant."""
    tenant_id = g.tenant_id
    tenant_tier = g.tenant.get("tier", "free")

    # Get all catalog entries
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT slug, name, description, category, tier_required,
                   icon, price_monthly, features, version
            FROM module_catalog
            ORDER BY category, name
            """
        )
        catalog = cur.fetchall()

    # Get tenant's enabled modules
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug, source, activated_at, trial_ends_at
            FROM tenant_modules
            WHERE tenant_id = %s AND enabled = TRUE
            """,
            (tenant_id,),
        )
        enabled = {r["module_slug"]: dict(r) for r in cur.fetchall()}

    tier_modules = get_modules_for_tier(tenant_tier)

    plugins = []
    for row in catalog:
        slug = row["slug"]
        activation = enabled.get(slug)
        is_active = activation is not None
        source = activation["source"] if activation else None

        # Determine availability
        included_in_tier = slug in tier_modules
        tier_required = row.get("tier_required", "free")
        needs_upgrade = not included_in_tier and tier_required != "addon"

        # Check trial status
        trial_active = False
        trial_ends = None
        if activation and activation.get("trial_ends_at"):
            trial_ends = activation["trial_ends_at"]
            if isinstance(trial_ends, str):
                trial_ends = datetime.fromisoformat(trial_ends)
            trial_active = trial_ends > datetime.utcnow()

        plugins.append({
            "slug": slug,
            "name": row["name"],
            "description": row.get("description", ""),
            "category": row.get("category", ""),
            "icon": row.get("icon", "box"),
            "tier_required": tier_required,
            "price_monthly": float(row["price_monthly"]) if row.get("price_monthly") else None,
            "features": row.get("features") or [],
            "version": row.get("version", "1.0.0"),
            "is_active": is_active,
            "source": source,
            "included_in_tier": included_in_tier,
            "needs_upgrade": needs_upgrade,
            "trial_active": trial_active,
            "trial_ends_at": trial_ends.isoformat() if trial_ends else None,
        })

    return jsonify({"plugins": plugins, "current_tier": tenant_tier})


# ---------------------------------------------------------------------------
# API: Plugin detail
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>")
@login_required
def plugin_detail(slug):
    """Return detailed info for a single plugin."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT slug, name, description, category, tier_required,
                   icon, price_monthly, features, version
            FROM module_catalog
            WHERE slug = %s
            """,
            (slug,),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"error": "Plugin not found"}), 404

    # Check activation status
    tenant_id = g.tenant_id
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug, source, activated_at, trial_ends_at
            FROM tenant_modules
            WHERE tenant_id = %s AND module_slug = %s AND enabled = TRUE
            """,
            (tenant_id, slug),
        )
        activation = cur.fetchone()

    tenant_tier = g.tenant.get("tier", "free")
    tier_modules = get_modules_for_tier(tenant_tier)
    included_in_tier = slug in tier_modules

    # Dependencies
    from flask import current_app
    plugin_meta = current_app.extensions.get("kbs_plugins", {}).get(slug, {})
    dependencies = plugin_meta.get("dependencies", [])

    result = {
        "slug": row["slug"],
        "name": row["name"],
        "description": row.get("description", ""),
        "category": row.get("category", ""),
        "icon": row.get("icon", "box"),
        "tier_required": row.get("tier_required", "free"),
        "price_monthly": float(row["price_monthly"]) if row.get("price_monthly") else None,
        "features": row.get("features") or [],
        "version": row.get("version", "1.0.0"),
        "is_active": activation is not None,
        "source": activation["source"] if activation else None,
        "included_in_tier": included_in_tier,
        "dependencies": dependencies,
    }

    return jsonify(result)


# ---------------------------------------------------------------------------
# API: Activate plugin
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>/activate", methods=["POST"])
@login_required
def activate_plugin(slug):
    """Activate a plugin for the current tenant.

    If the plugin is included in the tenant's tier, activates immediately.
    If it's an add-on, returns a Stripe checkout URL.
    """
    tenant_id = g.tenant_id
    tenant_tier = g.tenant.get("tier", "free")
    tier_modules = get_modules_for_tier(tenant_tier)

    # Verify plugin exists
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute("SELECT slug, tier_required FROM module_catalog WHERE slug = %s", (slug,))
        plugin = cur.fetchone()

    if not plugin:
        return jsonify({"error": "Plugin not found"}), 404

    # If included in current tier, activate immediately
    if slug in tier_modules:
        activate_module(tenant_id, slug, source="tier_included")
        return jsonify({"status": "activated", "source": "tier_included"})

    # Check if tier upgrade is needed vs add-on purchase
    tier_required = plugin.get("tier_required", "free")
    if tier_required in ("business", "enterprise") and tier_required != "addon":
        return jsonify({
            "status": "upgrade_required",
            "required_tier": tier_required,
            "message": f"Upgrade to {tier_required.title()} to access this plugin.",
        }), 402

    # Add-on -- create Stripe checkout
    try:
        from core.stripe_checkout import create_addon_checkout

        result = create_addon_checkout(
            tenant_id=tenant_id,
            plugin_slug=slug,
            customer_email=current_user.email,
        )
        return jsonify({"status": "checkout", "checkout_url": result["url"]})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# API: Start trial
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>/trial", methods=["POST"])
@login_required
def start_trial(slug):
    """Start a 14-day trial of a plugin."""
    tenant_id = g.tenant_id

    # Verify plugin exists
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute("SELECT slug FROM module_catalog WHERE slug = %s", (slug,))
        if not cur.fetchone():
            return jsonify({"error": "Plugin not found"}), 404

    # Check if already active
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug, source, trial_ends_at
            FROM tenant_modules
            WHERE tenant_id = %s AND module_slug = %s
            """,
            (tenant_id, slug),
        )
        existing = cur.fetchone()

    if existing and existing.get("source") == "trial":
        return jsonify({"error": "Trial already used for this plugin"}), 409

    if existing and existing.get("source") in ("tier_included", "addon_purchase"):
        return jsonify({"error": "Plugin is already active"}), 409

    # Activate with trial source
    trial_end = datetime.utcnow() + timedelta(days=14)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled, source, activated_at, trial_ends_at)
            VALUES (%s, %s, TRUE, 'trial', NOW(), %s)
            ON CONFLICT (tenant_id, module_slug)
            DO UPDATE SET
                enabled = TRUE,
                source = 'trial',
                activated_at = NOW(),
                trial_ends_at = %s,
                deactivated_at = NULL
            """,
            (tenant_id, slug, trial_end, trial_end),
        )

    logger.info("Started 14-day trial of %s for tenant %s", slug, tenant_id)

    return jsonify({
        "status": "trial_started",
        "plugin": slug,
        "trial_ends_at": trial_end.isoformat(),
    })


# ---------------------------------------------------------------------------
# API: Deactivate plugin
# ---------------------------------------------------------------------------


@marketplace_bp.route("/api/plugins/<slug>/deactivate", methods=["POST"])
@login_required
def deactivate_plugin(slug):
    """Deactivate a plugin for the current tenant."""
    tenant_id = g.tenant_id

    # Don't allow deactivating tier-included modules
    tenant_tier = g.tenant.get("tier", "free")
    tier_modules = get_modules_for_tier(tenant_tier)
    if slug in tier_modules:
        return jsonify({
            "error": "Cannot deactivate a module included in your tier.",
        }), 400

    deactivate_module(tenant_id, slug)
    logger.info("Deactivated plugin %s for tenant %s", slug, tenant_id)

    return jsonify({"status": "deactivated", "plugin": slug})
```

- [ ] **Step 2: Write marketplace API tests**

Create `tests/test_marketplace_api.py`:

```python
"""Tests for marketplace API endpoints."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_g():
    """Mock Flask g with tenant context."""
    with patch("core.marketplace.g") as mock_g:
        mock_g.tenant_id = 1
        mock_g.tenant = {"id": 1, "tier": "free", "slug": "test-co"}
        yield mock_g


@pytest.fixture
def _mock_user():
    """Mock current_user."""
    with patch("core.marketplace.current_user") as mock_user:
        mock_user.is_authenticated = True
        mock_user.email = "test@example.com"
        mock_user.id = 1
        yield mock_user


class TestListPlugins:
    def test_returns_all_catalog_entries(self, client, _mock_g, _mock_user):
        catalog = [
            {
                "slug": "crm",
                "name": "CRM",
                "description": "Contact management",
                "category": "core",
                "tier_required": "free",
                "icon": "users",
                "price_monthly": None,
                "features": ["contacts", "segments"],
                "version": "1.0.0",
            },
        ]
        enabled = [{"module_slug": "crm", "source": "tier_included", "activated_at": None, "trial_ends_at": None}]

        with patch("core.marketplace.get_db_cursor") as mock_ctx:
            mock_cur = MagicMock()
            mock_cur.fetchall.side_effect = [catalog, enabled]
            mock_cur.fetchone.return_value = None
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.get("/marketplace/api/plugins")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "plugins" in data
        assert data["current_tier"] == "free"


class TestActivatePlugin:
    def test_tier_included_activates_immediately(self, client, _mock_g, _mock_user):
        with patch("core.marketplace.get_db_cursor") as mock_ctx, \
             patch("core.marketplace.activate_module") as mock_act, \
             patch("core.marketplace.get_modules_for_tier") as mock_tier:
            mock_tier.return_value = {"crm", "invoicing"}
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"slug": "crm", "tier_required": "free"}
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.post("/marketplace/api/plugins/crm/activate")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "activated"

    def test_upgrade_required_returns_402(self, client, _mock_g, _mock_user):
        with patch("core.marketplace.get_db_cursor") as mock_ctx, \
             patch("core.marketplace.get_modules_for_tier") as mock_tier:
            mock_tier.return_value = {"crm", "invoicing"}
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"slug": "appointments", "tier_required": "business"}
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.post("/marketplace/api/plugins/appointments/activate")

        assert resp.status_code == 402


class TestStartTrial:
    def test_trial_starts_successfully(self, client, _mock_g, _mock_user):
        with patch("core.marketplace.get_db_cursor") as mock_ctx:
            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [
                {"slug": "appointments"},
                None,
            ]
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.post("/marketplace/api/plugins/appointments/trial")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "trial_started"
        assert "trial_ends_at" in data

    def test_duplicate_trial_returns_409(self, client, _mock_g, _mock_user):
        with patch("core.marketplace.get_db_cursor") as mock_ctx:
            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [
                {"slug": "appointments"},
                {"module_slug": "appointments", "source": "trial", "trial_ends_at": None},
            ]
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.post("/marketplace/api/plugins/appointments/trial")

        assert resp.status_code == 409


class TestDeactivatePlugin:
    def test_addon_deactivates(self, client, _mock_g, _mock_user):
        with patch("core.marketplace.get_modules_for_tier") as mock_tier, \
             patch("core.marketplace.deactivate_module") as mock_deact:
            mock_tier.return_value = {"crm"}

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.post("/marketplace/api/plugins/salon/deactivate")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "deactivated"

    def test_tier_included_cannot_deactivate(self, client, _mock_g, _mock_user):
        with patch("core.marketplace.get_modules_for_tier") as mock_tier:
            mock_tier.return_value = {"crm", "invoicing"}

            with patch("core.marketplace.login_required", lambda f: f):
                resp = client.post("/marketplace/api/plugins/crm/deactivate")

        assert resp.status_code == 400
```

- [ ] **Step 3: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_marketplace_api.py -v
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/marketplace.py tests/test_marketplace_api.py && git commit -m "feat(marketplace): full plugin catalog API with activate/trial/deactivate"
```

---

## Task 4: Marketplace UI Template

**Files:**
- Rewrite: `shared/templates/marketplace.html`

- [ ] **Step 1: Rewrite the marketplace template**

Replace `shared/templates/marketplace.html` with the full marketplace UI featuring plugin cards, filters by category/tier/status, search, plugin detail modal with activate/trial/deactivate/upgrade actions, tier badge colors, and current plan indicator. The template uses the `/marketplace/api/plugins` endpoint and the `esc()` helper function to sanitize all dynamic content before DOM insertion.

Key UI components:
- Grid of plugin cards with icon, name, description, tier badge, status dot
- Search input + category/tier/status dropdown filters
- Detail modal with features list, pricing, action buttons
- All dynamic content sanitized via `esc()` (creates text node, reads innerHTML)
- Responsive grid: `repeat(auto-fill, minmax(280px, 1fr))`

The template JS calls these marketplace API endpoints:
- `GET /marketplace/api/plugins` -- load all plugins
- `POST /marketplace/api/plugins/{slug}/activate` -- activate or get checkout URL
- `POST /marketplace/api/plugins/{slug}/trial` -- start 14-day trial
- `POST /marketplace/api/plugins/{slug}/deactivate` -- deactivate plugin

Use `document.createTextNode()` and DOM methods instead of innerHTML for user-generated content, or sanitize via the `esc()` helper that creates a temporary div with textContent and reads back innerHTML.

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add shared/templates/marketplace.html && git commit -m "feat(marketplace): full marketplace UI with cards, filters, detail modal"
```

---

## Task 5: Client Onboarding Wizard

**Files:**
- Create: `core/onboarding.py`
- Create: `shared/templates/onboarding.html`
- Modify: `core/app.py`
- Create: `tests/test_onboarding.py`

- [ ] **Step 1: Create core/onboarding.py**

```python
"""
core/onboarding.py -- Multi-step onboarding wizard for new tenants.

Steps:
  1. Business profile (name, industry, timezone, logo)
  2. Industry recommendation (auto-suggest bundle)
  3. Pick tier (pricing comparison)
  4. Stripe checkout (or skip for free)
  5. Guided setup checklist
"""

import json
import logging
from datetime import datetime

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

onboarding_bp = Blueprint(
    "onboarding", __name__, template_folder="../shared/templates"
)

# Industry -> recommended bundle mapping
INDUSTRY_BUNDLES = {
    "salon": {
        "name": "Salon Suite",
        "tier": "business",
        "plugins": ["appointments", "crm", "invoicing", "salon"],
        "description": "Everything a salon needs: online booking, client management, and invoicing.",
    },
    "electrical": {
        "name": "Electrical Contractor Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "electrical", "contracts"],
        "description": "Job tracking, quoting, invoicing, and contract management.",
    },
    "plumbing": {
        "name": "Plumbing Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "plumbing", "contracts"],
        "description": "Dispatch, invoicing, and contract management for plumbers.",
    },
    "photography": {
        "name": "Photography Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "photography", "appointments"],
        "description": "Booking, client galleries, invoicing, and CRM.",
    },
    "construction": {
        "name": "Construction Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "construction", "contracts"],
        "description": "Project management, quoting, and contract tracking.",
    },
    "limo": {
        "name": "Limo & Transport Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "limo", "appointments"],
        "description": "Reservation management, dispatch, and billing.",
    },
    "mechanical": {
        "name": "Mechanical Services Suite",
        "tier": "business",
        "plugins": ["crm", "invoicing", "mechanical", "contracts"],
        "description": "Work orders, quoting, and service tracking.",
    },
    "retail": {
        "name": "Retail Starter",
        "tier": "business",
        "plugins": ["crm", "invoicing", "store"],
        "description": "Online store, inventory, and customer management.",
    },
    "consulting": {
        "name": "Consulting Starter",
        "tier": "business",
        "plugins": ["crm", "invoicing", "appointments", "contracts"],
        "description": "Client management, scheduling, and invoicing.",
    },
    "other": {
        "name": "General Business",
        "tier": "free",
        "plugins": ["crm", "invoicing"],
        "description": "Core CRM and invoicing to get started.",
    },
}


@onboarding_bp.route("/")
@login_required
def index():
    """Render the onboarding wizard."""
    return render_template("onboarding.html")


@onboarding_bp.route("/api/progress", methods=["GET"])
@login_required
def get_progress():
    """Return the tenant's current onboarding progress."""
    tenant = g.tenant
    settings = tenant.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)

    return jsonify({
        "current_step": settings.get("onboarding_step", 1),
        "complete": settings.get("onboarding_complete", False),
        "industry": settings.get("industry", ""),
        "timezone": settings.get("timezone", ""),
        "logo_url": settings.get("logo_url", ""),
        "checklist": settings.get("onboarding_checklist", {}),
    })


@onboarding_bp.route("/api/profile", methods=["POST"])
@login_required
def save_profile():
    """Step 1: Save business profile (name, industry, timezone)."""
    data = request.get_json() or {}
    industry = data.get("industry", "other").lower().strip()
    timezone = data.get("timezone", "America/Toronto").strip()
    business_name = data.get("business_name", "").strip()

    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        updates = {
            "industry": industry,
            "timezone": timezone,
            "onboarding_step": 2,
        }
        if business_name:
            cur.execute(
                "UPDATE tenants SET name = %s, updated_at = NOW() WHERE id = %s",
                (business_name, tenant_id),
            )
        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (json.dumps(updates), tenant_id),
        )

    return jsonify({"status": "ok", "step": 2})


@onboarding_bp.route("/api/recommendation", methods=["GET"])
@login_required
def get_recommendation():
    """Step 2: Return industry-based bundle recommendation."""
    settings = g.tenant.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)

    industry = settings.get("industry", "other")
    bundle = INDUSTRY_BUNDLES.get(industry, INDUSTRY_BUNDLES["other"])

    return jsonify({
        "industry": industry,
        "bundle": bundle,
        "all_industries": list(INDUSTRY_BUNDLES.keys()),
    })


@onboarding_bp.route("/api/select-tier", methods=["POST"])
@login_required
def select_tier():
    """Step 3: Select a tier. Returns checkout URL for paid tiers, or activates free."""
    data = request.get_json() or {}
    tier = data.get("tier", "free").lower().strip()
    tenant_id = g.tenant_id

    # Update onboarding step
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (json.dumps({"onboarding_step": 4, "selected_tier": tier}), tenant_id),
        )

    if tier == "free":
        # Skip checkout, go to step 5
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE tenants
                SET settings = COALESCE(settings, '{}'::jsonb) || '{"onboarding_step": 5}'::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (tenant_id,),
            )
        return jsonify({"status": "ok", "step": 5, "tier": "free"})

    # Create Stripe checkout
    try:
        from core.stripe_checkout import create_subscription_checkout

        result = create_subscription_checkout(
            tenant_id=tenant_id,
            tier=tier,
            customer_email=current_user.email,
            success_url=f"{request.host_url}onboarding?step=5&payment=success",
            cancel_url=f"{request.host_url}onboarding?step=3&payment=cancelled",
        )
        return jsonify({"status": "checkout", "checkout_url": result["url"], "tier": tier})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@onboarding_bp.route("/api/checklist", methods=["POST"])
@login_required
def update_checklist():
    """Step 5: Update a checklist item completion status."""
    data = request.get_json() or {}
    item = data.get("item", "")
    done = data.get("done", False)
    tenant_id = g.tenant_id

    if not item:
        return jsonify({"error": "item is required"}), 400

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute("SELECT settings FROM tenants WHERE id = %s", (tenant_id,))
        row = cur.fetchone()
        settings = row["settings"] if row and row["settings"] else {}
        if isinstance(settings, str):
            settings = json.loads(settings)

        checklist = settings.get("onboarding_checklist", {})
        checklist[item] = done
        settings["onboarding_checklist"] = checklist

        cur.execute(
            "UPDATE tenants SET settings = %s::jsonb, updated_at = NOW() WHERE id = %s",
            (json.dumps(settings), tenant_id),
        )

    return jsonify({"status": "ok", "checklist": checklist})


@onboarding_bp.route("/api/complete", methods=["POST"])
@login_required
def complete_onboarding():
    """Mark onboarding as complete."""
    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb)
                || '{"onboarding_complete": true, "onboarding_step": 6}'::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (tenant_id,),
        )

    return jsonify({"status": "ok", "complete": True})
```

- [ ] **Step 2: Create shared/templates/onboarding.html**

Create the multi-step onboarding wizard template with 5 steps:
1. Business profile form (name, industry dropdown, timezone dropdown)
2. Industry recommendation card showing suggested bundle
3. Pricing comparison grid (Free/Business/Enterprise)
4. Payment redirect (auto-redirects to Stripe)
5. Setup checklist (import contacts, create invoice, setup booking, build website, invite team)

Progress bar at top shows steps 1-5 with active/done states. Uses onboarding API endpoints:
- `GET /onboarding/api/progress`
- `POST /onboarding/api/profile`
- `GET /onboarding/api/recommendation`
- `POST /onboarding/api/select-tier`
- `POST /onboarding/api/checklist`
- `POST /onboarding/api/complete`

- [ ] **Step 3: Register onboarding blueprint in app.py**

Add after the marketplace blueprint registration in `core/app.py`:

```python
    # Onboarding blueprint
    from core.onboarding import onboarding_bp

    app.register_blueprint(onboarding_bp, url_prefix="/onboarding")
```

- [ ] **Step 4: Write onboarding tests**

Create `tests/test_onboarding.py`:

```python
"""Tests for onboarding wizard API."""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_tenant():
    with patch("core.onboarding.g") as mock_g:
        mock_g.tenant_id = 1
        mock_g.tenant = {
            "id": 1,
            "tier": "free",
            "slug": "test-co",
            "settings": {"onboarding_step": 1},
        }
        yield mock_g


@pytest.fixture
def _mock_user():
    with patch("core.onboarding.current_user") as mock_user:
        mock_user.is_authenticated = True
        mock_user.email = "test@example.com"
        mock_user.id = 1
        yield mock_user


class TestOnboardingProgress:
    def test_returns_current_step(self, client, _mock_tenant, _mock_user):
        with patch("core.onboarding.login_required", lambda f: f):
            resp = client.get("/onboarding/api/progress")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_step"] == 1
        assert data["complete"] is False


class TestSaveProfile:
    def test_saves_industry_and_advances(self, client, _mock_tenant, _mock_user):
        with patch("core.onboarding.get_db_cursor") as mock_ctx, \
             patch("core.onboarding.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.post(
                "/onboarding/api/profile",
                json={"business_name": "Acme Corp", "industry": "salon", "timezone": "America/Toronto"},
            )

        assert resp.status_code == 200
        assert resp.get_json()["step"] == 2


class TestRecommendation:
    def test_returns_bundle_for_industry(self, client, _mock_tenant, _mock_user):
        _mock_tenant.tenant["settings"] = {"industry": "salon"}
        with patch("core.onboarding.login_required", lambda f: f):
            resp = client.get("/onboarding/api/recommendation")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["bundle"]["name"] == "Salon Suite"
        assert "appointments" in data["bundle"]["plugins"]

    def test_unknown_industry_returns_other(self, client, _mock_tenant, _mock_user):
        _mock_tenant.tenant["settings"] = {"industry": "space_tourism"}
        with patch("core.onboarding.login_required", lambda f: f):
            resp = client.get("/onboarding/api/recommendation")
        data = resp.get_json()
        assert data["bundle"]["name"] == "General Business"


class TestSelectTier:
    def test_free_tier_skips_checkout(self, client, _mock_tenant, _mock_user):
        with patch("core.onboarding.get_db_cursor") as mock_ctx, \
             patch("core.onboarding.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.post(
                "/onboarding/api/select-tier",
                json={"tier": "free"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["step"] == 5
        assert data["tier"] == "free"

    def test_business_tier_returns_checkout_url(self, client, _mock_tenant, _mock_user):
        with patch("core.onboarding.get_db_cursor") as mock_ctx, \
             patch("core.onboarding.login_required", lambda f: f), \
             patch("core.stripe_checkout.create_subscription_checkout") as mock_sub:
            mock_cur = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_sub.return_value = {"url": "https://checkout.stripe.com/test", "session_id": "cs_test"}

            resp = client.post(
                "/onboarding/api/select-tier",
                json={"tier": "business"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "checkout"
        assert "checkout_url" in data


class TestChecklist:
    def test_updates_checklist_item(self, client, _mock_tenant, _mock_user):
        with patch("core.onboarding.get_db_cursor") as mock_ctx, \
             patch("core.onboarding.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"settings": {"onboarding_checklist": {}}}
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.post(
                "/onboarding/api/checklist",
                json={"item": "import_contacts", "done": True},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["checklist"]["import_contacts"] is True


class TestCompleteOnboarding:
    def test_marks_complete(self, client, _mock_tenant, _mock_user):
        with patch("core.onboarding.get_db_cursor") as mock_ctx, \
             patch("core.onboarding.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.post("/onboarding/api/complete")

        assert resp.status_code == 200
        assert resp.get_json()["complete"] is True
```

- [ ] **Step 5: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_onboarding.py -v
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/onboarding.py shared/templates/onboarding.html core/app.py tests/test_onboarding.py && git commit -m "feat(onboarding): multi-step wizard with industry bundles and Stripe checkout"
```

---

## Task 6: Subdomain Provisioning

**Files:**
- Create: `core/subdomain_manager.py`
- Modify: `core/auth.py` (wire into signup)
- Modify: `core/app.py` (custom domain route)
- Create: `tests/test_subdomain_manager.py`

- [ ] **Step 1: Create core/subdomain_manager.py**

```python
"""
core/subdomain_manager.py -- Subdomain and custom domain provisioning via Hostinger DNS API.

Provides:
- provision_subdomain(slug) -- creates A record for {slug}.kytranempowerment.com
- provision_custom_domain(domain, tenant_id) -- for paid clients
- check_subdomain_health(slug) -- DNS resolution check
- check_custom_domain_health(domain) -- DNS resolution check
"""

import logging
import os
import socket
from typing import Optional

import requests

from core.database import get_db_cursor

logger = logging.getLogger(__name__)


def _get_hostinger_api_key() -> str:
    return os.getenv("KBS_HOSTINGER_API_KEY", "")


def _get_base_domain() -> str:
    return os.getenv("KBS_BASE_DOMAIN", "kytranempowerment.com")


def _get_subdomain_target() -> str:
    return os.getenv("KBS_SUBDOMAIN_TARGET", "192.168.1.200")


def _get_api_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_hostinger_api_key()}",
        "Content-Type": "application/json",
    }


def provision_subdomain(slug: str) -> dict:
    """Create an A record for {slug}.{base_domain} pointing to the KBS server.

    Args:
        slug: Tenant slug (e.g. 'acme-corp').

    Returns:
        Dict with 'subdomain', 'fqdn', 'status'.

    Raises:
        ValueError: If slug is empty or API key is not set.
        requests.RequestException: On API failure.
    """
    if not slug:
        raise ValueError("Slug is required for subdomain provisioning")

    api_key = _get_hostinger_api_key()
    if not api_key:
        logger.warning("KBS_HOSTINGER_API_KEY not set -- skipping DNS provisioning for %s", slug)
        return {"subdomain": slug, "fqdn": f"{slug}.{_get_base_domain()}", "status": "skipped"}

    base_domain = _get_base_domain()
    target = _get_subdomain_target()
    fqdn = f"{slug}.{base_domain}"

    url = f"https://api.hostinger.com/api/dns/v1/domains/{base_domain}/records"
    payload = {
        "records": [
            {
                "type": "A",
                "name": slug,
                "content": target,
                "ttl": 3600,
            }
        ]
    }

    try:
        resp = requests.put(url, json=payload, headers=_get_api_headers(), timeout=15)
        resp.raise_for_status()
        logger.info("Provisioned subdomain %s -> %s", fqdn, target)
        return {"subdomain": slug, "fqdn": fqdn, "status": "provisioned", "target": target}
    except requests.RequestException as exc:
        logger.error("Failed to provision subdomain %s: %s", fqdn, exc)
        raise


def provision_custom_domain(domain: str, tenant_id: int) -> dict:
    """Register a custom domain for a paid tenant.

    Records the domain on the tenant settings. DNS must be configured by the client.

    Args:
        domain: Custom domain (e.g. 'app.acme.com').
        tenant_id: Tenant ID.

    Returns:
        Dict with 'domain', 'status', 'instructions'.
    """
    if not domain:
        raise ValueError("Domain is required")

    target = _get_subdomain_target()

    with get_db_cursor(commit=True) as (conn, cur):
        import json

        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (json.dumps({"custom_domain": domain}), tenant_id),
        )

    logger.info("Registered custom domain %s for tenant %s", domain, tenant_id)

    return {
        "domain": domain,
        "tenant_id": tenant_id,
        "status": "registered",
        "instructions": f"Point your domain {domain} to {target} via A record.",
    }


def check_subdomain_health(slug: str) -> dict:
    """Check if a subdomain resolves correctly.

    Args:
        slug: Tenant slug.

    Returns:
        Dict with 'fqdn', 'resolves', 'ip', 'expected_ip', 'correct'.
    """
    base_domain = _get_base_domain()
    fqdn = f"{slug}.{base_domain}"
    target = _get_subdomain_target()

    try:
        ip = socket.gethostbyname(fqdn)
        resolves = True
        correct = ip == target
    except socket.gaierror:
        ip = None
        resolves = False
        correct = False

    return {
        "fqdn": fqdn,
        "resolves": resolves,
        "ip": ip,
        "expected_ip": target,
        "correct": correct,
    }


def check_custom_domain_health(domain: str) -> dict:
    """Check if a custom domain resolves to the KBS server."""
    target = _get_subdomain_target()

    try:
        ip = socket.gethostbyname(domain)
        resolves = True
        correct = ip == target
    except socket.gaierror:
        ip = None
        resolves = False
        correct = False

    return {
        "domain": domain,
        "resolves": resolves,
        "ip": ip,
        "expected_ip": target,
        "correct": correct,
    }
```

- [ ] **Step 2: Wire subdomain provisioning into auth signup**

Add after `create_tenant_schema(tenant_id)` in `core/auth.py` signup route (around line 243):

```python
        # Provision subdomain (non-blocking -- failure doesn't block signup)
        try:
            from core.subdomain_manager import provision_subdomain

            provision_subdomain(slug)
        except Exception:
            pass  # Non-fatal -- subdomain can be provisioned later
```

- [ ] **Step 3: Add custom domain settings route to app.py**

Add a route in `core/app.py` for connecting custom domains:

```python
    # Custom domain API
    @app.route("/api/settings/domain", methods=["POST"])
    def connect_custom_domain():
        from flask import g, jsonify, request
        from flask_login import current_user as cu

        if not cu.is_authenticated:
            return jsonify({"error": "authentication required"}), 401

        data = request.get_json() or {}
        domain = data.get("domain", "").strip()
        if not domain:
            return jsonify({"error": "domain is required"}), 400

        tenant_tier = g.tenant.get("tier", "free")
        if tenant_tier == "free":
            return jsonify({"error": "Custom domains require a paid plan"}), 402

        try:
            from core.subdomain_manager import provision_custom_domain
            result = provision_custom_domain(domain, g.tenant_id)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
```

- [ ] **Step 4: Write subdomain manager tests**

Create `tests/test_subdomain_manager.py`:

```python
"""Tests for subdomain provisioning (mocked Hostinger API)."""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("KBS_HOSTINGER_API_KEY", "test-api-key")
    monkeypatch.setenv("KBS_BASE_DOMAIN", "kytranempowerment.com")
    monkeypatch.setenv("KBS_SUBDOMAIN_TARGET", "192.168.1.200")


class TestProvisionSubdomain:
    def test_creates_dns_record(self):
        from core.subdomain_manager import provision_subdomain

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("core.subdomain_manager.requests.put", return_value=mock_resp) as mock_put:
            result = provision_subdomain("acme-corp")

        assert result["subdomain"] == "acme-corp"
        assert result["fqdn"] == "acme-corp.kytranempowerment.com"
        assert result["status"] == "provisioned"
        mock_put.assert_called_once()

    def test_empty_slug_raises(self):
        from core.subdomain_manager import provision_subdomain

        with pytest.raises(ValueError, match="Slug is required"):
            provision_subdomain("")

    def test_no_api_key_skips(self, monkeypatch):
        monkeypatch.setenv("KBS_HOSTINGER_API_KEY", "")
        from core.subdomain_manager import provision_subdomain

        result = provision_subdomain("test-co")
        assert result["status"] == "skipped"

    def test_api_failure_raises(self):
        from core.subdomain_manager import provision_subdomain
        import requests as req_lib

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_lib.RequestException("DNS API error")

        with patch("core.subdomain_manager.requests.put", return_value=mock_resp):
            with pytest.raises(req_lib.RequestException):
                provision_subdomain("fail-co")


class TestProvisionCustomDomain:
    def test_records_custom_domain(self):
        from core.subdomain_manager import provision_custom_domain

        with patch("core.subdomain_manager.get_db_cursor") as mock_ctx:
            mock_cur = MagicMock()
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = provision_custom_domain("app.acme.com", tenant_id=1)

        assert result["domain"] == "app.acme.com"
        assert result["status"] == "registered"
        assert "instructions" in result

    def test_empty_domain_raises(self):
        from core.subdomain_manager import provision_custom_domain

        with pytest.raises(ValueError, match="Domain is required"):
            provision_custom_domain("", tenant_id=1)


class TestSubdomainHealth:
    def test_resolves_correctly(self):
        from core.subdomain_manager import check_subdomain_health

        with patch("core.subdomain_manager.socket.gethostbyname", return_value="192.168.1.200"):
            result = check_subdomain_health("acme-corp")

        assert result["resolves"] is True
        assert result["correct"] is True
        assert result["ip"] == "192.168.1.200"

    def test_does_not_resolve(self):
        from core.subdomain_manager import check_subdomain_health
        import socket

        with patch("core.subdomain_manager.socket.gethostbyname", side_effect=socket.gaierror):
            result = check_subdomain_health("nonexistent")

        assert result["resolves"] is False
        assert result["correct"] is False

    def test_resolves_wrong_ip(self):
        from core.subdomain_manager import check_subdomain_health

        with patch("core.subdomain_manager.socket.gethostbyname", return_value="1.2.3.4"):
            result = check_subdomain_health("wrong-ip")

        assert result["resolves"] is True
        assert result["correct"] is False
```

- [ ] **Step 5: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_subdomain_manager.py -v
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/subdomain_manager.py core/auth.py core/app.py tests/test_subdomain_manager.py && git commit -m "feat(dns): subdomain provisioning via Hostinger API + custom domain support"
```

---

## Task 7: Client Dashboard Enhancement

**Files:**
- Create: `core/dashboard_stats.py`
- Modify: `shared/templates/dashboard.html`
- Modify: `core/app.py`
- Create: `tests/test_dashboard_stats.py`

- [ ] **Step 1: Create core/dashboard_stats.py**

```python
"""
core/dashboard_stats.py -- Dashboard statistics aggregation API.

Aggregates data from active plugins for the tenant dashboard:
contacts, invoices, appointments, notifications, quick actions.
"""

import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify
from flask_login import login_required

from core.database import get_db_cursor, set_tenant_search_path

logger = logging.getLogger(__name__)

dashboard_stats_bp = Blueprint("dashboard_stats", __name__)


@dashboard_stats_bp.route("/api/dashboard/stats")
@login_required
def get_stats():
    """Aggregate dashboard stats from all active plugins."""
    tenant_id = g.tenant_id
    tenant = g.tenant
    settings = tenant.get("settings") or {}
    if isinstance(settings, str):
        settings = json.loads(settings)

    stats = {
        "tenant_name": tenant.get("name", ""),
        "tier": tenant.get("tier", "free"),
        "onboarding_complete": settings.get("onboarding_complete", False),
        "checklist": settings.get("onboarding_checklist", {}),
    }

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)

        # Contact count
        try:
            cur.execute("SELECT COUNT(*) AS cnt FROM crm_contacts")
            stats["total_contacts"] = cur.fetchone()["cnt"]
        except Exception:
            stats["total_contacts"] = 0

        # Invoice stats
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'unpaid' OR status = 'overdue') AS outstanding,
                    COALESCE(SUM(balance_due) FILTER (WHERE status IN ('unpaid', 'overdue')), 0) AS outstanding_amount
                FROM invoices
                """
            )
            inv = cur.fetchone()
            stats["total_invoices"] = inv["total"]
            stats["outstanding_invoices"] = inv["outstanding"]
            stats["outstanding_amount"] = float(inv["outstanding_amount"])
        except Exception:
            stats["total_invoices"] = 0
            stats["outstanding_invoices"] = 0
            stats["outstanding_amount"] = 0.0

        # Upcoming appointments (next 7 days)
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM appointments
                WHERE start_time >= NOW() AND start_time <= NOW() + INTERVAL '7 days'
                    AND status != 'cancelled'
                """
            )
            stats["upcoming_appointments"] = cur.fetchone()["cnt"]
        except Exception:
            stats["upcoming_appointments"] = 0

        # Recent revenue (last 30 days)
        try:
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS revenue
                FROM invoice_payments
                WHERE created_at >= NOW() - INTERVAL '30 days'
                """
            )
            stats["revenue_30d"] = float(cur.fetchone()["revenue"])
        except Exception:
            stats["revenue_30d"] = 0.0

        # Open help desk tickets
        try:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM help_tickets WHERE status IN ('open', 'in_progress')"
            )
            stats["open_tickets"] = cur.fetchone()["cnt"]
        except Exception:
            stats["open_tickets"] = 0

    # Quick actions based on enabled plugins
    from core.tenant import get_enabled_modules

    enabled = get_enabled_modules()
    actions = []
    if "crm" in enabled:
        actions.append({"label": "Add Contact", "url": "/plugins/crm/contacts/new", "icon": "users"})
    if "invoicing" in enabled:
        actions.append({"label": "Create Invoice", "url": "/plugins/invoicing/new", "icon": "invoice"})
    if "appointments" in enabled:
        actions.append({"label": "Book Appointment", "url": "/plugins/appointments/new", "icon": "calendar"})
    if "website-builder" in enabled:
        actions.append({"label": "Edit Website", "url": "/plugins/website-builder/", "icon": "globe"})
    if "store" in enabled:
        actions.append({"label": "View Store", "url": "/plugins/store/", "icon": "store"})
    stats["quick_actions"] = actions

    return jsonify(stats)
```

- [ ] **Step 2: Register dashboard_stats blueprint in app.py**

Add after onboarding registration in `core/app.py`:

```python
    # Dashboard stats API
    from core.dashboard_stats import dashboard_stats_bp

    app.register_blueprint(dashboard_stats_bp)
```

- [ ] **Step 3: Enhance shared/templates/dashboard.html**

Enhance the dashboard template with:
- Stats cards row: Contacts, Outstanding Invoices, Revenue (30d), Upcoming Appointments, Open Tickets
- Onboarding banner (shown if incomplete) with link to /onboarding
- Quick actions sidebar based on enabled plugins
- Active plugins grid from existing `plugins` template variable
- Responsive layout: stats grid collapses on mobile, actions/plugins stack on 768px
- Loads stats from `GET /api/dashboard/stats` on page load

- [ ] **Step 4: Write dashboard stats tests**

Create `tests/test_dashboard_stats.py`:

```python
"""Tests for dashboard stats API."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_tenant():
    with patch("core.dashboard_stats.g") as mock_g:
        mock_g.tenant_id = 1
        mock_g.tenant = {"id": 1, "name": "Test Co", "tier": "business", "settings": {"onboarding_complete": True}}
        yield mock_g


@pytest.fixture
def _mock_user():
    with patch("core.dashboard_stats.login_required", lambda f: f):
        yield


class TestDashboardStats:
    def test_returns_tenant_info(self, client, _mock_tenant, _mock_user):
        with patch("core.dashboard_stats.get_db_cursor") as mock_ctx, \
             patch("core.dashboard_stats.set_tenant_search_path"), \
             patch("core.dashboard_stats.get_enabled_modules", return_value=["crm", "invoicing"]):
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"cnt": 0, "total": 0, "outstanding": 0, "outstanding_amount": 0, "revenue": 0}
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get("/api/dashboard/stats")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["tenant_name"] == "Test Co"
        assert data["tier"] == "business"
        assert "quick_actions" in data

    def test_quick_actions_based_on_enabled_plugins(self, client, _mock_tenant, _mock_user):
        with patch("core.dashboard_stats.get_db_cursor") as mock_ctx, \
             patch("core.dashboard_stats.set_tenant_search_path"), \
             patch("core.dashboard_stats.get_enabled_modules", return_value=["crm"]):
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"cnt": 0, "total": 0, "outstanding": 0, "outstanding_amount": 0, "revenue": 0}
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get("/api/dashboard/stats")

        data = resp.get_json()
        action_labels = [a["label"] for a in data["quick_actions"]]
        assert "Add Contact" in action_labels
        assert "Create Invoice" not in action_labels
```

- [ ] **Step 5: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_dashboard_stats.py -v
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/dashboard_stats.py shared/templates/dashboard.html core/app.py tests/test_dashboard_stats.py && git commit -m "feat(dashboard): enhanced client dashboard with stats, actions, and onboarding"
```

---

## Task 8: Admin Dashboard (Kytran Empowerment)

**Files:**
- Create: `core/admin_dashboard.py`
- Create: `shared/templates/admin_dashboard.html`
- Modify: `core/app.py`
- Create: `tests/test_admin_dashboard.py`

- [ ] **Step 1: Create core/admin_dashboard.py**

```python
"""
core/admin_dashboard.py -- Platform admin metrics for Kytran Empowerment.

Routes require the 'owner' role (platform-level admin).
"""

import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, render_template, session
from flask_login import current_user, login_required

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, template_folder="../shared/templates")


def _require_owner(fn):
    """Decorator: require tenant_role == 'owner'."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from flask import abort

        role = session.get("tenant_role", "")
        if role != "owner":
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


@admin_bp.route("/dashboard")
@login_required
@_require_owner
def dashboard():
    return render_template("admin_dashboard.html")


@admin_bp.route("/api/metrics")
@login_required
@_require_owner
def metrics():
    """Return platform-wide metrics."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        # Total tenants
        cur.execute("SELECT COUNT(*) AS cnt FROM tenants WHERE is_active = TRUE")
        total_tenants = cur.fetchone()["cnt"]

        # New signups (last 30 days)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM tenants WHERE created_at >= NOW() - INTERVAL '30 days'"
        )
        new_signups_30d = cur.fetchone()["cnt"]

        # Tier breakdown
        cur.execute(
            """
            SELECT tier, COUNT(*) AS cnt
            FROM tenants
            WHERE is_active = TRUE
            GROUP BY tier
            ORDER BY tier
            """
        )
        tier_breakdown = {r["tier"]: r["cnt"] for r in cur.fetchall()}

        # MRR calculation
        tier_prices = {"free": 0, "business": 49, "enterprise": 149}
        mrr = sum(tier_prices.get(t, 0) * c for t, c in tier_breakdown.items())

        # Add-on count
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM tenant_modules
            WHERE source = 'addon_purchase' AND enabled = TRUE
            """
        )
        addon_count = cur.fetchone()["cnt"]
        addon_mrr = addon_count * 29  # average add-on price

        # Churn (tenants deactivated in last 30 days)
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM tenants
            WHERE is_active = FALSE
                AND updated_at >= NOW() - INTERVAL '30 days'
            """
        )
        churned_30d = cur.fetchone()["cnt"]

        # Plugin activation heatmap
        cur.execute(
            """
            SELECT module_slug, COUNT(*) AS cnt
            FROM tenant_modules
            WHERE enabled = TRUE
            GROUP BY module_slug
            ORDER BY cnt DESC
            """
        )
        plugin_heatmap = [{"slug": r["module_slug"], "count": r["cnt"]} for r in cur.fetchall()]

        # Client health
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE last_login >= NOW() - INTERVAL '7 days') AS active_7d,
                COUNT(*) FILTER (WHERE last_login >= NOW() - INTERVAL '30 days') AS active_30d,
                COUNT(*) FILTER (WHERE last_login < NOW() - INTERVAL '30 days' OR last_login IS NULL) AS inactive
            FROM users
            WHERE is_active = TRUE
            """
        )
        health_row = cur.fetchone()
        client_health = {
            "active_7d": health_row["active_7d"] if health_row else 0,
            "active_30d": health_row["active_30d"] if health_row else 0,
            "inactive": health_row["inactive"] if health_row else 0,
        }

        # Active trials
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM tenants WHERE trial_ends_at IS NOT NULL AND trial_ends_at > NOW()"
        )
        active_trials = cur.fetchone()["cnt"]

    return jsonify({
        "total_tenants": total_tenants,
        "new_signups_30d": new_signups_30d,
        "tier_breakdown": tier_breakdown,
        "mrr": mrr,
        "addon_mrr": addon_mrr,
        "total_mrr": mrr + addon_mrr,
        "churned_30d": churned_30d,
        "churn_rate": round(churned_30d / max(total_tenants, 1) * 100, 1),
        "plugin_heatmap": plugin_heatmap,
        "client_health": client_health,
        "active_trials": active_trials,
    })
```

- [ ] **Step 2: Create shared/templates/admin_dashboard.html**

Create the admin dashboard template with:
- KPI cards row: Total Tenants, MRR (CAD), New Signups (30d), Churn Rate, Active Trials
- Tier Breakdown horizontal bar chart
- Plugin Popularity horizontal bar chart (top 15)
- Client Health cards: Active (7d), Active (30d), Inactive
- Responsive: 2-column layout collapses to 1 at 768px
- Loads from `GET /admin/api/metrics`

- [ ] **Step 3: Register admin blueprint in app.py**

Add after dashboard_stats registration in `core/app.py`:

```python
    # Admin dashboard
    from core.admin_dashboard import admin_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")
```

- [ ] **Step 4: Write admin dashboard tests**

Create `tests/test_admin_dashboard.py`:

```python
"""Tests for admin dashboard metrics API."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_owner_session():
    with patch("core.admin_dashboard.session") as mock_session:
        mock_session.get.return_value = "owner"
        yield mock_session


@pytest.fixture
def _mock_user():
    with patch("core.admin_dashboard.current_user") as mock_user:
        mock_user.is_authenticated = True
        mock_user.id = 1
        yield mock_user


class TestAdminMetrics:
    def test_returns_platform_metrics(self, client, _mock_owner_session, _mock_user):
        with patch("core.admin_dashboard.get_db_cursor") as mock_ctx, \
             patch("core.admin_dashboard.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [
                {"cnt": 10},
                {"cnt": 3},
                {"cnt": 2},
                {"cnt": 1},
                {"active_7d": 8, "active_30d": 9, "inactive": 1},
                {"cnt": 2},
            ]
            mock_cur.fetchall.side_effect = [
                [{"tier": "free", "cnt": 5}, {"tier": "business", "cnt": 4}, {"tier": "enterprise", "cnt": 1}],
                [{"module_slug": "crm", "cnt": 10}, {"module_slug": "invoicing", "cnt": 8}],
            ]
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get("/admin/api/metrics")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_tenants"] == 10
        assert data["total_mrr"] > 0
        assert "plugin_heatmap" in data
        assert "client_health" in data

    def test_non_owner_gets_403(self, client, _mock_user):
        with patch("core.admin_dashboard.session") as mock_session, \
             patch("core.admin_dashboard.login_required", lambda f: f):
            mock_session.get.return_value = "member"
            resp = client.get("/admin/api/metrics")

        assert resp.status_code == 403
```

- [ ] **Step 5: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_admin_dashboard.py -v
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/admin_dashboard.py shared/templates/admin_dashboard.html core/app.py tests/test_admin_dashboard.py && git commit -m "feat(admin): platform admin dashboard with MRR, churn, plugin heatmap"
```

---

## Task 9: Team Management

**Files:**
- Create: `core/team_management.py`
- Modify: `core/app.py`
- Create: `tests/test_team_management.py`

- [ ] **Step 1: Create core/team_management.py**

```python
"""
core/team_management.py -- Team member invite, role, and removal for tenants.

Routes:
  POST   /api/team/invite       -- invite by email
  GET    /api/team              -- list team members
  PUT    /api/team/<id>/role    -- change role (owner only)
  DELETE /api/team/<id>         -- remove from tenant
  GET    /auth/accept-invite/<token> -- accept invite
"""

import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, redirect, request, session, url_for
from flask_login import current_user, login_required

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

team_bp = Blueprint("team", __name__)

VALID_ROLES = {"admin", "member", "viewer"}


@team_bp.route("/api/team/invite", methods=["POST"])
@login_required
def invite_member():
    """Invite a user to the current tenant by email."""
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    role = data.get("role", "member").strip().lower()

    if not email:
        return jsonify({"error": "email is required"}), 400

    if role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}"}), 400

    tenant_role = session.get("tenant_role", "")
    if tenant_role not in ("owner", "admin"):
        return jsonify({"error": "Only owners and admins can invite team members"}), 403

    tenant_id = g.tenant_id
    token = secrets.token_urlsafe(32)

    # Check for existing pending invite
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM team_invites WHERE tenant_id = %s AND email = %s AND status = 'pending'",
            (tenant_id, email),
        )
        if cur.fetchone():
            return jsonify({"error": "An invite is already pending for this email"}), 409

    # Check if already a member
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT tu.user_id
            FROM tenant_users tu JOIN users u ON u.id = tu.user_id
            WHERE tu.tenant_id = %s AND u.email = %s
            """,
            (tenant_id, email),
        )
        if cur.fetchone():
            return jsonify({"error": "User is already a member of this workspace"}), 409

    # Create invite
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO team_invites (tenant_id, email, role, invited_by, token, status, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', NOW() + INTERVAL '7 days')
            RETURNING id
            """,
            (tenant_id, email, role, current_user.id, token),
        )
        invite_id = cur.fetchone()[0]

    invite_url = f"{request.host_url}auth/accept-invite/{token}"

    logger.info("Created team invite %s for %s (tenant %s)", invite_id, email, tenant_id)

    return jsonify({
        "status": "invited",
        "invite_id": invite_id,
        "email": email,
        "role": role,
        "invite_url": invite_url,
    })


@team_bp.route("/api/team", methods=["GET"])
@login_required
def list_members():
    """List all team members and pending invites for the current tenant."""
    tenant_id = g.tenant_id

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT u.id, u.email, u.username AS name, tu.role, u.last_login, u.created_at
            FROM tenant_users tu JOIN users u ON u.id = tu.user_id
            WHERE tu.tenant_id = %s
            ORDER BY tu.role, u.username
            """,
            (tenant_id,),
        )
        members = []
        for row in cur.fetchall():
            members.append({
                "id": row["id"],
                "email": row["email"],
                "name": row["name"],
                "role": row["role"],
                "last_login": row["last_login"].isoformat() if row.get("last_login") else None,
                "joined": row["created_at"].isoformat() if row.get("created_at") else None,
            })

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, email, role, created_at, expires_at
            FROM team_invites
            WHERE tenant_id = %s AND status = 'pending' AND expires_at > NOW()
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        invites = []
        for row in cur.fetchall():
            invites.append({
                "id": row["id"],
                "email": row["email"],
                "role": row["role"],
                "invited_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
                "status": "pending",
            })

    return jsonify({"members": members, "pending_invites": invites})


@team_bp.route("/api/team/<int:user_id>/role", methods=["PUT"])
@login_required
def change_role(user_id):
    """Change a team member's role. Owner only."""
    data = request.get_json() or {}
    new_role = data.get("role", "").strip().lower()

    if new_role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}"}), 400

    if session.get("tenant_role", "") != "owner":
        return jsonify({"error": "Only the owner can change roles"}), 403

    if user_id == current_user.id:
        return jsonify({"error": "Cannot change your own role"}), 400

    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE tenant_users SET role = %s WHERE tenant_id = %s AND user_id = %s RETURNING user_id",
            (new_role, tenant_id, user_id),
        )
        if not cur.fetchone():
            return jsonify({"error": "User not found in this workspace"}), 404

    logger.info("Changed role of user %s to %s (tenant %s)", user_id, new_role, tenant_id)
    return jsonify({"status": "ok", "user_id": user_id, "role": new_role})


@team_bp.route("/api/team/<int:user_id>", methods=["DELETE"])
@login_required
def remove_member(user_id):
    """Remove a team member. Owner and admin only. Cannot remove the owner."""
    tenant_role = session.get("tenant_role", "")
    if tenant_role not in ("owner", "admin"):
        return jsonify({"error": "Only owners and admins can remove members"}), 403

    if user_id == current_user.id:
        return jsonify({"error": "Cannot remove yourself"}), 400

    tenant_id = g.tenant_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND role != 'owner' RETURNING user_id",
            (tenant_id, user_id),
        )
        if not cur.fetchone():
            return jsonify({"error": "User not found or cannot remove the owner"}), 404

    logger.info("Removed user %s from tenant %s", user_id, tenant_id)
    return jsonify({"status": "removed", "user_id": user_id})


@team_bp.route("/auth/accept-invite/<token>")
def accept_invite(token):
    """Accept a team invite via token link."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id, tenant_id, email, role, expires_at FROM team_invites WHERE token = %s AND status = 'pending'",
            (token,),
        )
        invite = cur.fetchone()

    if not invite:
        return jsonify({"error": "Invalid or expired invite"}), 404

    if invite["expires_at"] and invite["expires_at"] < datetime.utcnow():
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE team_invites SET status = 'expired' WHERE id = %s", (invite["id"],))
        return jsonify({"error": "This invite has expired"}), 410

    if current_user.is_authenticated:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO tenant_users (tenant_id, user_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                (invite["tenant_id"], current_user.id, invite["role"]),
            )
            cur.execute(
                "UPDATE team_invites SET status = 'accepted', accepted_at = NOW() WHERE id = %s",
                (invite["id"],),
            )
        session["tenant_id"] = invite["tenant_id"]
        session["tenant_role"] = invite["role"]
        return redirect(url_for("dashboard"))

    session["pending_invite_token"] = token
    return redirect(url_for("auth.signup") + f"?invite={token}")
```

- [ ] **Step 2: Register team blueprint in app.py**

Add after admin blueprint registration in `core/app.py`:

```python
    # Team management
    from core.team_management import team_bp

    app.register_blueprint(team_bp)
```

- [ ] **Step 3: Write team management tests**

Create `tests/test_team_management.py`:

```python
"""Tests for team management API."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_tenant():
    with patch("core.team_management.g") as mock_g:
        mock_g.tenant_id = 1
        mock_g.tenant = {"id": 1, "tier": "business"}
        yield mock_g


@pytest.fixture
def _mock_user():
    with patch("core.team_management.current_user") as mock_user:
        mock_user.is_authenticated = True
        mock_user.email = "owner@example.com"
        mock_user.id = 1
        yield mock_user


@pytest.fixture
def _mock_owner_session():
    with patch("core.team_management.session") as mock_s:
        mock_s.get.return_value = "owner"
        yield mock_s


class TestInviteMember:
    def test_creates_invite(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.get_db_cursor") as mock_ctx, \
             patch("core.team_management.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [None, None, (42,)]
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.post(
                "/api/team/invite",
                json={"email": "new@example.com", "role": "member"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "invited"
        assert data["email"] == "new@example.com"
        assert "invite_url" in data

    def test_invalid_role_returns_400(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.login_required", lambda f: f):
            resp = client.post(
                "/api/team/invite",
                json={"email": "new@example.com", "role": "superadmin"},
            )
        assert resp.status_code == 400

    def test_missing_email_returns_400(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.login_required", lambda f: f):
            resp = client.post("/api/team/invite", json={"role": "member"})
        assert resp.status_code == 400


class TestListMembers:
    def test_returns_members_and_invites(self, client, _mock_tenant, _mock_user):
        with patch("core.team_management.get_db_cursor") as mock_ctx, \
             patch("core.team_management.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_cur.fetchall.side_effect = [
                [{"id": 1, "email": "owner@example.com", "name": "Owner", "role": "owner", "last_login": None, "created_at": None}],
                [],
            ]
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.get("/api/team")

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["members"]) == 1
        assert data["members"][0]["role"] == "owner"


class TestChangeRole:
    def test_owner_changes_role(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.get_db_cursor") as mock_ctx, \
             patch("core.team_management.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (2,)
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.put("/api/team/2/role", json={"role": "admin"})

        assert resp.status_code == 200
        assert resp.get_json()["role"] == "admin"

    def test_cannot_change_own_role(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.login_required", lambda f: f):
            resp = client.put("/api/team/1/role", json={"role": "viewer"})
        assert resp.status_code == 400


class TestRemoveMember:
    def test_removes_non_owner(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.get_db_cursor") as mock_ctx, \
             patch("core.team_management.login_required", lambda f: f):
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (2,)
            mock_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.delete("/api/team/2")

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "removed"

    def test_cannot_remove_self(self, client, _mock_tenant, _mock_user, _mock_owner_session):
        with patch("core.team_management.login_required", lambda f: f):
            resp = client.delete("/api/team/1")
        assert resp.status_code == 400
```

- [ ] **Step 4: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_team_management.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add core/team_management.py core/app.py tests/test_team_management.py && git commit -m "feat(team): team invite, role management, and member removal"
```

---

## Task 10: Integration Tests

**Files:**
- Create: `tests/test_wave3_integration.py`

- [ ] **Step 1: Write full SaaS resale flow integration tests**

Create `tests/test_wave3_integration.py`:

```python
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
        from core.stripe_checkout import create_subscription_checkout

        mock_s = MagicMock()
        mock_s.url = "https://checkout.stripe.com/test"
        mock_s.id = "cs_test"

        with patch("core.stripe_checkout.stripe") as ms, \
             patch("core.stripe_checkout._save_subscription_checkout"):
            ms.checkout.Session.create.return_value = mock_s
            result = create_subscription_checkout(
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
```

- [ ] **Step 2: Run all Wave 3 tests**

```bash
docker exec kbs_app python -m pytest tests/test_subscription_checkout.py tests/test_subscription_webhooks.py tests/test_marketplace_api.py tests/test_onboarding.py tests/test_subdomain_manager.py tests/test_dashboard_stats.py tests/test_admin_dashboard.py tests/test_team_management.py tests/test_wave3_integration.py -v
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite && git add tests/test_wave3_integration.py && git commit -m "test(wave3): full SaaS resale integration tests covering all flows"
```

---

## Summary

Wave 3 delivers 10 tasks that together create a self-serve SaaS resale infrastructure:

| Task | Deliverable | Files |
|------|-------------|-------|
| 1 | Subscription checkout (business/enterprise/add-on) | stripe_checkout.py, config.py |
| 2 | Webhook handlers (created/updated/deleted/failed) | stripe_billing.py, migration |
| 3 | Marketplace API (list/detail/activate/trial/deactivate) | marketplace.py |
| 4 | Marketplace UI (cards, filters, detail modal) | marketplace.html |
| 5 | Onboarding wizard (5 steps, industry bundles) | onboarding.py, onboarding.html |
| 6 | Subdomain provisioning (Hostinger DNS API) | subdomain_manager.py |
| 7 | Client dashboard (stats, actions, plugins) | dashboard_stats.py, dashboard.html |
| 8 | Admin dashboard (MRR, churn, heatmap, health) | admin_dashboard.py |
| 9 | Team management (invite, role, remove) | team_management.py |
| 10 | Integration tests (full SaaS resale flow) | test_wave3_integration.py |

**New files:** 11 Python modules + 3 templates + 1 migration + 9 test files = 24 files
**Modified files:** 5 (stripe_checkout, stripe_billing, config, app, auth)
**Total test files:** 9 new test files covering all endpoints
