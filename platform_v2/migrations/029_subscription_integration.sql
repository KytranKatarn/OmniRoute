-- Migration 029: Subscription Integration Tables
-- Creates user_oauth_connections, user_api_keys, and adds billing trial fields
-- All statements are idempotent

-- ============================================================
-- 1. user_oauth_connections
-- ============================================================
CREATE TABLE IF NOT EXISTS user_oauth_connections (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider                VARCHAR(64) NOT NULL,
    provider_user_id        VARCHAR(256),
    email                   VARCHAR(256),
    display_name            VARCHAR(256),
    access_token_encrypted  TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at        TIMESTAMP,
    connected_at            TIMESTAMP DEFAULT NOW(),
    disconnected_at         TIMESTAMP,
    UNIQUE (user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_user_oauth_connections_user_id
    ON user_oauth_connections (user_id);

COMMENT ON TABLE user_oauth_connections IS
    'Stores OAuth provider connections per user (Google, GitHub, etc.)';
COMMENT ON COLUMN user_oauth_connections.access_token_encrypted IS
    'AES-encrypted access token — never store plaintext';
COMMENT ON COLUMN user_oauth_connections.refresh_token_encrypted IS
    'AES-encrypted refresh token — never store plaintext';

-- ============================================================
-- 2. user_api_keys
-- ============================================================
CREATE TABLE IF NOT EXISTS user_api_keys (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash    VARCHAR(128) NOT NULL UNIQUE,
    key_prefix  VARCHAR(8)  NOT NULL,
    product     VARCHAR(64) NOT NULL,
    name        VARCHAR(128),
    created_at  TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    revoked_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id
    ON user_api_keys (user_id);

CREATE INDEX IF NOT EXISTS idx_user_api_keys_key_hash
    ON user_api_keys (key_hash);

COMMENT ON TABLE user_api_keys IS
    'Per-user API keys for platform product access';
COMMENT ON COLUMN user_api_keys.key_hash IS
    'SHA-256 hash of the raw API key — raw key is never stored';
COMMENT ON COLUMN user_api_keys.key_prefix IS
    'First 8 chars of the raw key shown in UI for identification';

-- ============================================================
-- 3. billing_subscriptions — add trial/override columns
-- ============================================================
ALTER TABLE billing_subscriptions
    ADD COLUMN IF NOT EXISTS expires_at   TIMESTAMP;

ALTER TABLE billing_subscriptions
    ADD COLUMN IF NOT EXISTS granted_by   INTEGER REFERENCES users(id);

ALTER TABLE billing_subscriptions
    ADD COLUMN IF NOT EXISTS revoked_at   TIMESTAMP;

COMMENT ON COLUMN billing_subscriptions.expires_at IS
    'Trial expiration timestamp; NULL = permanent subscription';
COMMENT ON COLUMN billing_subscriptions.granted_by IS
    'admin user_id who granted a trial or manual override; NULL = self-service';
COMMENT ON COLUMN billing_subscriptions.revoked_at IS
    'Timestamp when a trial or override was revoked; NULL = still active';
