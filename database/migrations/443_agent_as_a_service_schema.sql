-- Migration 443: Agent-as-a-Service (AaaS) schema — Project #297, task #2475
-- Idempotent: safe to run multiple times
--
-- Adds the data model for the AaaS delivery pipeline (ADR #869 deliverable model,
-- ADR #870 build parameters):
--   1. aaas_orders          — order/spec lifecycle, the normalized agent "brief" as JSONB
--   2. agents.org_id        — tenancy column (NULL = internal ARCHIE agent; non-NULL = client-owned)
--   3. v_internal_agents    — the single SAFE internal surface (guardrail against client-agent leakage)
--   4. billing_product_plans seed rows for product_id='aaas' (Accessible SMB monthly hosting tiers)
--
-- worker_type stays 'ai' for client agents (no new enum — ADR #870 decision 3); org_id distinguishes them.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. aaas_orders — commissioning order + lifecycle
--    Lifecycle (status): submitted -> quoted -> paid_build -> building -> qa_review
--                        -> client_review -> live -> (renewing | suspended | offboarded)
--    Status is a plain VARCHAR (no CHECK) so new states never require a migration.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aaas_orders (
    id                     SERIAL PRIMARY KEY,
    org_id                 INTEGER REFERENCES organizations(id),
    contact_email          VARCHAR(255) NOT NULL,
    contact_name           VARCHAR(255),
    company_name           VARCHAR(255),
    tier                   VARCHAR(50)  NOT NULL DEFAULT 'starter',   -- starter | pro | enterprise
    brief                  JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- normalized agent brief (build contract)
    status                 VARCHAR(50)  NOT NULL DEFAULT 'submitted',
    build_fee_cents        INTEGER,
    monthly_cents          INTEGER,
    currency               VARCHAR(3)   NOT NULL DEFAULT 'CAD',
    stripe_checkout_id     VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    built_agent_id         INTEGER REFERENCES agents(id),             -- set once the agent is built
    -- lifecycle timestamps (UTC, set by the app/worker on each transition)
    submitted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    quoted_at              TIMESTAMPTZ,
    paid_build_at          TIMESTAMPTZ,
    building_at            TIMESTAMPTZ,
    qa_review_at           TIMESTAMPTZ,
    client_review_at       TIMESTAMPTZ,
    live_at                TIMESTAMPTZ,
    offboarded_at          TIMESTAMPTZ,
    notes                  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- worker finds orders awaiting a concierge build trigger / draining by state
CREATE INDEX IF NOT EXISTS idx_aaas_orders_status        ON aaas_orders (status);
CREATE INDEX IF NOT EXISTS idx_aaas_orders_org_id        ON aaas_orders (org_id);
CREATE INDEX IF NOT EXISTS idx_aaas_orders_contact_email ON aaas_orders (contact_email);
CREATE INDEX IF NOT EXISTS idx_aaas_orders_built_agent   ON aaas_orders (built_agent_id);

-- ---------------------------------------------------------------------------
-- 2. agents.org_id — tenancy (NULL = internal ARCHIE agent)
-- ---------------------------------------------------------------------------
ALTER TABLE agents ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES organizations(id);
CREATE INDEX IF NOT EXISTS idx_agents_org_id ON agents (org_id);
COMMENT ON COLUMN agents.org_id IS 'AaaS tenancy: NULL = internal ARCHIE agent; non-NULL = client-owned agent scoped to that organization.';

-- ---------------------------------------------------------------------------
-- 3. v_internal_agents — the SAFE internal surface.
--    Internal roster/dispatch/manifest code should read this view instead of `agents`
--    directly, so a forgotten `org_id IS NULL` filter cannot leak a client agent.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_internal_agents AS
    SELECT * FROM agents WHERE org_id IS NULL;

-- ---------------------------------------------------------------------------
-- 4. billing_product_plans seed — product_id='aaas' monthly hosting tiers (CAD).
--    amount_cents = MONTHLY hosting; one-time build fee lives per-order on
--    aaas_orders.build_fee_cents. stripe_price_id minted later (starts '').
--    Idempotent via WHERE NOT EXISTS (no assumption about a unique constraint).
-- ---------------------------------------------------------------------------
INSERT INTO billing_product_plans (product_id, tier_name, tier_rank, stripe_price_id, amount_cents, currency, billing_interval, is_active)
SELECT 'aaas', 'starter', 10, '', 4900, 'CAD', 'month', true
WHERE NOT EXISTS (SELECT 1 FROM billing_product_plans WHERE product_id='aaas' AND tier_name='starter');

INSERT INTO billing_product_plans (product_id, tier_name, tier_rank, stripe_price_id, amount_cents, currency, billing_interval, is_active)
SELECT 'aaas', 'pro', 20, '', 14900, 'CAD', 'month', true
WHERE NOT EXISTS (SELECT 1 FROM billing_product_plans WHERE product_id='aaas' AND tier_name='pro');

INSERT INTO billing_product_plans (product_id, tier_name, tier_rank, stripe_price_id, amount_cents, currency, billing_interval, is_active)
SELECT 'aaas', 'enterprise', 30, '', 49900, 'CAD', 'month', true
WHERE NOT EXISTS (SELECT 1 FROM billing_product_plans WHERE product_id='aaas' AND tier_name='enterprise');

COMMIT;
