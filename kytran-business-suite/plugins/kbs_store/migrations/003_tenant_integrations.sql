-- Store plugin migration 003 — per-tenant integration credentials.
-- Allows each tenant to connect their own Stripe/Printful accounts.
-- All statements are idempotent. Run inside tenant schema.

CREATE TABLE IF NOT EXISTS tenant_integrations (
    id          SERIAL PRIMARY KEY,
    service     VARCHAR(50) NOT NULL,
    credentials JSONB NOT NULL DEFAULT '{}',
    status      VARCHAR(20) DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive', 'error')),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (service)
);

COMMENT ON TABLE tenant_integrations IS 'Per-tenant API credentials for Stripe, Printful, etc.';
COMMENT ON COLUMN tenant_integrations.credentials IS 'JSONB: secret_key, publishable_key, webhook_secret (Stripe) or api_key (Printful)';
