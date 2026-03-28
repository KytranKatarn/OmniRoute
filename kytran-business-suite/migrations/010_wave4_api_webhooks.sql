-- Wave 4: API keys and webhooks — run in public schema.

-- ---------------------------------------------------------------------------
-- API Keys (per-tenant)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_keys (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash     VARCHAR(128) NOT NULL UNIQUE,
    key_prefix   VARCHAR(12) NOT NULL,
    name         VARCHAR(255) NOT NULL,
    permissions  JSONB DEFAULT '["read"]',
    rate_limit   INTEGER DEFAULT 1000,
    is_active    BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant   ON api_keys (tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash     ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_active   ON api_keys (is_active) WHERE is_active = TRUE;

-- Rate limit tracking (sliding window)
CREATE TABLE IF NOT EXISTS api_rate_limits (
    id         SERIAL PRIMARY KEY,
    key_id     INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    window_key VARCHAR(20) NOT NULL,
    count      INTEGER DEFAULT 1,
    UNIQUE (key_id, window_key)
);

-- ---------------------------------------------------------------------------
-- Tenant Webhooks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_webhooks (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    events     JSONB NOT NULL DEFAULT '["*"]',
    secret     VARCHAR(128) NOT NULL,
    is_active  BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON tenant_webhooks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_active ON tenant_webhooks (is_active) WHERE is_active = TRUE;

-- Webhook delivery log
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id           SERIAL PRIMARY KEY,
    webhook_id   INTEGER NOT NULL REFERENCES tenant_webhooks(id) ON DELETE CASCADE,
    event_type   VARCHAR(100) NOT NULL,
    payload      JSONB NOT NULL,
    response_code INTEGER,
    response_body TEXT,
    delivered_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries (webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_date    ON webhook_deliveries (delivered_at);
