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
