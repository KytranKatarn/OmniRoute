-- Migration 306: Replace 'news' OAuth client with WTF clients
-- Idempotent: ON CONFLICT DO UPDATE, and deactivate obsolete 'news' client

UPDATE oauth_clients SET is_active = false WHERE client_id = 'news';

INSERT INTO oauth_clients (client_id, client_secret, redirect_uri, name, is_active)
VALUES
    ('wtf-consumer', encode(gen_random_bytes(32), 'hex'),
     'https://what-the-fact.com/auth/kytran/callback', 'What The Fact Consumer', true),
    ('wtf-tech',     encode(gen_random_bytes(32), 'hex'),
     'https://what-the-fact.tech/auth/kytran/callback', 'What The Fact Tech', true)
ON CONFLICT (client_id) DO UPDATE SET
    redirect_uri = EXCLUDED.redirect_uri,
    name         = EXCLUDED.name,
    is_active    = EXCLUDED.is_active;
