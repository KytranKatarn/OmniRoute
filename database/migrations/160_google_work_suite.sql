-- Migration 160: Google Work Suite — accounts, email cache, rules
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS google_accounts (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL,
    owner_id INTEGER NOT NULL,
    email VARCHAR(200) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    access_token TEXT,
    refresh_token TEXT,
    token_expiry TIMESTAMP,
    scopes TEXT,
    is_primary BOOLEAN DEFAULT TRUE,
    permission_level VARCHAR(20) DEFAULT 'full',
    last_sync_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS google_email_cache (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    gmail_id VARCHAR(100) NOT NULL,
    thread_id VARCHAR(100),
    subject TEXT,
    sender VARCHAR(200),
    recipients JSONB DEFAULT '[]',
    snippet TEXT,
    labels JSONB DEFAULT '[]',
    is_read BOOLEAN DEFAULT FALSE,
    is_starred BOOLEAN DEFAULT FALSE,
    has_attachments BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMP,
    cached_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_id, gmail_id)
);

CREATE TABLE IF NOT EXISTS google_email_rules (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    conditions JSONB NOT NULL,
    actions JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_google_accounts_owner ON google_accounts(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_google_email_cache_account ON google_email_cache(account_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_google_email_cache_thread ON google_email_cache(thread_id);
CREATE INDEX IF NOT EXISTS idx_google_email_rules_account ON google_email_rules(account_id);
