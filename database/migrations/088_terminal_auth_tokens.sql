-- Migration 088: Create terminal_auth_tokens table
-- Stores one-time authentication tokens for Claude Terminal (ttyd) access.
-- Users obtain a token from the platform, use it once to authenticate with
-- the ttyd auth proxy, and it is marked as used. Tokens expire after 60 seconds.

BEGIN;

-- 1. Create the terminal auth tokens table
CREATE TABLE IF NOT EXISTS terminal_auth_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(64) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN DEFAULT FALSE
);

-- 2. Create index for fast token lookups during authentication
CREATE INDEX IF NOT EXISTS idx_term_tokens_token
    ON terminal_auth_tokens(token);

COMMIT;
