-- OAuth provider tables for "Sign in with Kytran" standalone authentication
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/202_oauth_clients.sql

CREATE TABLE IF NOT EXISTS oauth_clients (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) UNIQUE NOT NULL,
    client_secret VARCHAR(128) NOT NULL,
    redirect_uri VARCHAR(512) NOT NULL,
    name VARCHAR(128) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(128) UNIQUE NOT NULL,
    client_id VARCHAR(64) NOT NULL REFERENCES oauth_clients(client_id),
    user_id INTEGER NOT NULL,
    redirect_uri VARCHAR(512) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_codes_code ON oauth_codes(code);
CREATE INDEX IF NOT EXISTS idx_oauth_codes_expires ON oauth_codes(expires_at);

-- Ensure pgcrypto is available for gen_random_bytes
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Pre-register Kytran System Operations as OAuth client
INSERT INTO oauth_clients (client_id, client_secret, redirect_uri, name)
VALUES (
    'kytran-sysops',
    encode(gen_random_bytes(32), 'hex'),
    'http://192.168.1.200:8085/auth/sso/callback',
    'Kytran System Operations'
) ON CONFLICT (client_id) DO NOTHING;
