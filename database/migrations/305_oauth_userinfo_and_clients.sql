-- Migration 305: Seed OAuth clients for standalone Kytran products
-- Idempotent: uses ON CONFLICT DO UPDATE

-- Ensure oauth_clients table exists (matches existing schema)
CREATE TABLE IF NOT EXISTS oauth_clients (
    id            SERIAL PRIMARY KEY,
    client_id     VARCHAR(64)  NOT NULL UNIQUE,
    client_secret VARCHAR(128) NOT NULL,
    redirect_uri  VARCHAR(512) NOT NULL,
    name          VARCHAR(128) NOT NULL,
    is_active     BOOLEAN DEFAULT true,
    created_at    TIMESTAMP DEFAULT now()
);

-- Ensure oauth_codes table exists (used by oauth_provider.py)
CREATE TABLE IF NOT EXISTS oauth_codes (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(128) NOT NULL UNIQUE,
    client_id    VARCHAR(64)  NOT NULL REFERENCES oauth_clients(client_id),
    user_id      INTEGER      NOT NULL,
    redirect_uri VARCHAR(512) NOT NULL,
    expires_at   TIMESTAMP    NOT NULL,
    used         BOOLEAN DEFAULT false,
    created_at   TIMESTAMP DEFAULT now()
);

-- Seed 6 OAuth clients for standalone products
INSERT INTO oauth_clients (client_id, client_secret, redirect_uri, name, is_active)
VALUES
    ('kso',          encode(gen_random_bytes(32), 'hex'), 'https://server.kytranempowerment.com/auth/callback',  'Kytran System Operations', true),
    ('kbs',          encode(gen_random_bytes(32), 'hex'), 'https://business.kytranempowerment.com/auth/callback', 'Kytran Business Suite',    true),
    ('gov-watch',    encode(gen_random_bytes(32), 'hex'), 'https://gov.kytranempowerment.com/auth/callback',      'Kytran Gov Watch',         true),
    ('news',         encode(gen_random_bytes(32), 'hex'), 'https://news.kytranempowerment.com/auth/callback',     'Kytran News',              true),
    ('market-watch', encode(gen_random_bytes(32), 'hex'), 'https://market.kytranempowerment.com/auth/callback',   'Kytran Market Watch',      true),
    ('kytran-mail',  encode(gen_random_bytes(32), 'hex'), 'https://mail.kytranempowerment.com/auth/callback',     'Kytran Mail',              true)
ON CONFLICT (client_id) DO UPDATE SET
    redirect_uri = EXCLUDED.redirect_uri,
    name         = EXCLUDED.name,
    is_active    = EXCLUDED.is_active;
