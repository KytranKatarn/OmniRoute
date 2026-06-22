-- 441_signal_idempotency.sql  (S6-P1-8a)
--
-- Idempotency foundation for S.I.G.N.A.L. LinkedIn publishing. A slow post that times
-- out (>180s cold) followed by a retry could currently double-publish. This records a
-- stable content+account+slot key at BOTH the sidecar task log and the publish ledger so
-- a duplicate publish becomes a no-op / constraint violation instead of a second post.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS. browser_task_log
-- already exists (migration 169) — we only add columns. Applied manually:
--   docker exec -i archie_database psql -U archie -d archie < 441_signal_idempotency.sql

BEGIN;

-- Sidecar task log: carry the caller idempotency key + a stable task_id + post metadata,
-- so a timed-out caller can look up "did this exact post already complete?".
ALTER TABLE browser_task_log
    ADD COLUMN IF NOT EXISTS task_id         varchar(36),
    ADD COLUMN IF NOT EXISTS idempotency_key varchar(64),
    ADD COLUMN IF NOT EXISTS post_metadata   jsonb;

CREATE INDEX IF NOT EXISTS idx_browser_task_log_idem
    ON browser_task_log (idempotency_key, agent_id)
    WHERE idempotency_key IS NOT NULL;

-- Publish ledger: a UNIQUE idempotency key per (account post_type, agent) turns a
-- duplicate publish into a constraint violation rather than a second LinkedIn post.
-- scheduled_post_id links back to the calendar slot (agent_content_posts).
ALTER TABLE linkedin_post_log
    ADD COLUMN IF NOT EXISTS idempotency_key   varchar(64),
    ADD COLUMN IF NOT EXISTS scheduled_post_id integer
        REFERENCES agent_content_posts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS task_id           varchar(36);

CREATE UNIQUE INDEX IF NOT EXISTS uq_linkedin_post_log_idem
    ON linkedin_post_log (idempotency_key, post_type, agent_id)
    WHERE idempotency_key IS NOT NULL;

-- Record (manual-apply convention; idempotent regardless of version column type).
INSERT INTO schema_migrations (version, description)
SELECT 441, 'S.I.G.N.A.L. idempotency: browser_task_log + linkedin_post_log keys (S6-P1-8a)'
WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = '441');

COMMIT;
