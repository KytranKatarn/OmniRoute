-- Phase A of Unified Subscription & Billing implementation plan
-- (docs/superpowers/plans/2026-04-17-unified-subscription-billing-implementation.md)
--
-- Aligns subscription_tiers with Decision #453 (6-Tier Model) and wires the
-- live Stripe product/price IDs from vault-note 256750 (2026-04-16).
--
-- Non-destructive: keeps old tiers enabled=false so user_subscriptions FK
-- references stay intact. A later cleanup pass will re-point users and
-- archive the legacy rows.

BEGIN;

-- 1. Add Stripe + KBS linking columns (idempotent)
ALTER TABLE subscription_tiers
    ADD COLUMN IF NOT EXISTS stripe_product_id       VARCHAR(64),
    ADD COLUMN IF NOT EXISTS stripe_price_id_monthly VARCHAR(64),
    ADD COLUMN IF NOT EXISTS stripe_price_id_yearly  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS currency                VARCHAR(3) DEFAULT 'cad',
    ADD COLUMN IF NOT EXISTS kbs_product_slug        VARCHAR(64);

-- 2. Retire the legacy 1.0 tier rows (keep for FK safety; don't delete)
UPDATE subscription_tiers
   SET enabled = FALSE,
       updated_at = NOW()
 WHERE name IN ('pro', 'business', 'enterprise')
   AND price_monthly IN (9.99, 29.99, 99.99)
   AND enabled = TRUE;

-- 3. Insert/update the Decision #453 tiers with live Stripe IDs
-- ON CONFLICT (name) DO UPDATE keeps the migration idempotent across re-runs.

INSERT INTO subscription_tiers (
    name, display_name, description,
    price_monthly, price_yearly, currency,
    features, limits, role_level, color, sort_order, enabled,
    stripe_product_id, stripe_price_id_monthly, kbs_product_slug
) VALUES
(
    'explorer',
    'Explorer',
    'Free tier (auto-activated on signup). Dashboard with gated modules + community tips.',
    0, 0, 'cad',
    '["Dashboard access", "Module previews (gated)", "Community tips", "A.R.C.H.I.E. Chat (basic)"]'::jsonb,
    '{"storage_mb": 500, "api_calls_daily": 100, "ai_agents": 0, "watch_products": 0}'::jsonb,
    10, '#6b7280', 10, TRUE,
    NULL, NULL, 'explorer'
),
(
    'starter',
    'Starter',
    'CRM, Invoicing, Store Builder, Content Studio, 1 Watch product, 5 AI agents.',
    299.00, 2990.00, 'cad',
    '["CRM", "Invoicing", "Store Builder", "Content Studio", "1 Watch product", "5 AI agents", "Standard support"]'::jsonb,
    '{"storage_mb": 10000, "api_calls_daily": 5000, "ai_agents": 5, "watch_products": 1}'::jsonb,
    20, '#22c55e', 20, TRUE,
    'prod_ULarbP2VrC0AqB', 'price_1TMtfi06cZ0yWDKJnCmKKeNu', 'starter'
),
(
    'professional',
    'Professional',
    'All Starter features plus Website Designer, Social Media, more Watch products, 15 AI agents.',
    799.00, 7990.00, 'cad',
    '["Everything in Starter", "Website Designer", "Social Media", "3 Watch products", "15 AI agents", "Priority support", "Advanced analytics"]'::jsonb,
    '{"storage_mb": 50000, "api_calls_daily": 25000, "ai_agents": 15, "watch_products": 3}'::jsonb,
    20, '#3b82f6', 30, TRUE,
    'prod_ULarkVTZDVxtz4', 'price_1TMtfi06cZ0yWDKJsocTKBAn', 'professional'
),
(
    'enterprise_plus',
    'Enterprise',
    'Full platform access — unlimited Watch products, unlimited AI agents, dedicated support.',
    1499.00, 14990.00, 'cad',
    '["Everything in Professional", "All Watch products", "Unlimited AI agents", "White-label options", "SLA guarantee", "Dedicated infrastructure", "24/7 priority support"]'::jsonb,
    '{"storage_mb": -1, "api_calls_daily": -1, "ai_agents": -1, "watch_products": -1}'::jsonb,
    20, '#ffd700', 40, TRUE,
    'prod_ULar6OoTAIyWzh', 'price_1TMtfj06cZ0yWDKJFfiyL6I0', 'enterprise_plus'
)
ON CONFLICT (name) DO UPDATE SET
    display_name            = EXCLUDED.display_name,
    description             = EXCLUDED.description,
    price_monthly           = EXCLUDED.price_monthly,
    price_yearly            = EXCLUDED.price_yearly,
    currency                = EXCLUDED.currency,
    features                = EXCLUDED.features,
    limits                  = EXCLUDED.limits,
    role_level              = EXCLUDED.role_level,
    color                   = EXCLUDED.color,
    sort_order              = EXCLUDED.sort_order,
    enabled                 = EXCLUDED.enabled,
    stripe_product_id       = EXCLUDED.stripe_product_id,
    stripe_price_id_monthly = EXCLUDED.stripe_price_id_monthly,
    kbs_product_slug        = EXCLUDED.kbs_product_slug,
    updated_at              = NOW();

-- 4. Helpful index for checkout lookups by Stripe price ID (webhook → tier)
CREATE INDEX IF NOT EXISTS idx_subscription_tiers_stripe_price_monthly
    ON subscription_tiers (stripe_price_id_monthly)
    WHERE stripe_price_id_monthly IS NOT NULL;

COMMIT;
