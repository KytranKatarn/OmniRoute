-- Migration 318: OAuth client registry deduplication (task #2067 scope a)
--
-- Disables two stale duplicate rows in oauth_clients that were never used
-- in production (0 rows in oauth_codes history):
--
--   market-watch  — duplicate of market-watch-viewer (24 successful auths)
--                   Stale row uses /auth/callback (non-standard path).
--   news          — duplicate of news-watch (5 successful auths).
--                   Stale row points to news.kytranempowerment.com — that
--                   subdomain doesn't exist; real product is at
--                   thenews.kytranempowerment.com (owned by news-watch).
--
-- Using UPDATE is_active=false (soft-disable) rather than DELETE so the
-- FK reference from oauth_codes is preserved and rows can be re-enabled if
-- some legacy integration surfaces. Idempotent via WHERE.
--
-- Out of scope for this migration (follow-up work for #2067 scope b):
--   - kytran-sysops  raw IP + HTTP callback → should move to
--                    https://server.kytranempowerment.com/auth/kytran/callback
--                    (also duplicate of kso; same client, different ID)
--   - kytran-mail    callback path inconsistency (/auth/callback vs
--                    standard /auth/kytran/callback)

BEGIN;

UPDATE oauth_clients
SET is_active = false
WHERE client_id IN ('market-watch', 'news')
  AND is_active = true;

-- Sanity: after run, these should be the only is_active=false rows
-- touched by this migration.
SELECT client_id, is_active, redirect_uri
FROM oauth_clients
WHERE client_id IN ('market-watch', 'news');

COMMIT;
