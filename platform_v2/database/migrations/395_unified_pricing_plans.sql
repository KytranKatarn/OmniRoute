-- Migration 395: Unified pricing plans registry (T3027)
-- New table: billing_product_plans
-- NOTE: subscription_plans already exists with a different legacy schema (plan registry).
-- This table is the canonical per-product Stripe price → tier mapping.

CREATE TABLE IF NOT EXISTS billing_product_plans (
    id                  SERIAL PRIMARY KEY,
    product_id          VARCHAR(64)  NOT NULL,           -- e.g. gov_watch, wtf, bundle_watch
    tier_name           VARCHAR(32)  NOT NULL,           -- free|starter|solo|team|agency|enterprise
    tier_rank           INTEGER      NOT NULL DEFAULT 0, -- numeric: free=0, starter=10, solo=30, team=40, agency=50, enterprise=99
    stripe_price_id     VARCHAR(128) NOT NULL DEFAULT '', -- populate from Stripe dashboard
    amount_cents        INTEGER      NOT NULL DEFAULT 0,
    currency            VARCHAR(3)   NOT NULL DEFAULT 'CAD',
    billing_interval    VARCHAR(10)  NOT NULL DEFAULT 'month',
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, tier_name)
);

CREATE INDEX IF NOT EXISTS idx_billing_product_plans_price_id
    ON billing_product_plans (stripe_price_id)
    WHERE stripe_price_id != '';

CREATE INDEX IF NOT EXISTS idx_billing_product_plans_product
    ON billing_product_plans (product_id, is_active);

-- Seed canonical plan rows (stripe_price_id starts empty — populate from Stripe dashboard)
INSERT INTO billing_product_plans (product_id, tier_name, tier_rank, amount_cents, currency, billing_interval) VALUES
-- Gov Watch
('gov_watch',    'free',     0,  0,     'CAD', 'month'),
('gov_watch',    'solo',     30, 999,   'CAD', 'month'),  -- $9.99
('gov_watch',    'team',     40, 2999,  'CAD', 'month'),  -- $29.99
('gov_watch',    'agency',   50, 7999,  'CAD', 'month'),  -- $79.99

-- WTF (What The Fact)
('wtf',          'free',     0,  0,     'CAD', 'month'),
('wtf',          'starter',  10, 499,   'CAD', 'month'),  -- $4.99

-- Civic Watch
('civic_watch',  'free',     0,  0,     'CAD', 'month'),
('civic_watch',  'starter',  10, 499,   'CAD', 'month'),  -- $4.99

-- Legal Watch
('legal_watch',  'free',     0,  0,     'CAD', 'month'),
('legal_watch',  'starter',  10, 499,   'CAD', 'month'),  -- $4.99

-- Market Watch
('market_watch', 'free',     0,  0,     'CAD', 'month'),
('market_watch', 'starter',  10, 499,   'CAD', 'month'),  -- $4.99

-- Watch Bundle (4-product: gov + civic + legal + market)
('bundle_watch', 'solo',     30, 1299,  'CAD', 'month'),  -- $12.99

-- Intelligence Bundle (5-product: 4 Watch + WTF)
('bundle_intelligence', 'team', 40, 1999, 'CAD', 'month') -- $19.99
ON CONFLICT (product_id, tier_name) DO NOTHING;
