-- 443_signal_engagement_ledger.sql  (S7-P1-4a)
--
-- Fleet-safe engagement: a GLOBAL ledger keyed UNIQUE(post_urn, acting_agent_id, action)
-- replaces the per-account autonomy_approval_queue dedup (which did not scale past one
-- agent) so >=2 fleet agents never both engage the same post and no agent double-engages.
-- Plus per-agent daily action budget + jittered pacing counters on the registry.
--
-- Idempotent (CREATE TABLE/INDEX IF NOT EXISTS, ADD COLUMN IF NOT EXISTS). Applied manually:
--   docker exec -i archie_database psql -U archie -d archie < 443_signal_engagement_ledger.sql

BEGIN;

CREATE TABLE IF NOT EXISTS linkedin_engagement_ledger (
    id               serial PRIMARY KEY,
    post_urn         varchar(120) NOT NULL,
    acting_agent_id  integer      NOT NULL,
    action           varchar(24)  NOT NULL,                 -- like | comment | share
    status           varchar(16)  NOT NULL DEFAULT 'pending', -- pending | executed | failed
    approval_id      integer,
    comment_text     text,
    similarity_score real,
    created_at       timestamptz  NOT NULL DEFAULT NOW(),
    executed_at      timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_engagement_ledger
    ON linkedin_engagement_ledger (post_urn, acting_agent_id, action);
CREATE INDEX IF NOT EXISTS idx_engagement_ledger_created
    ON linkedin_engagement_ledger (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_engagement_ledger_post
    ON linkedin_engagement_ledger (post_urn);

-- Per-agent engagement budget + pacing on the registry (reuse — do NOT make a new table).
ALTER TABLE agent_platform_accounts
    ADD COLUMN IF NOT EXISTS daily_action_budget integer DEFAULT 5,
    ADD COLUMN IF NOT EXISTS active_count_today  integer DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pacing_jitter_min_s integer DEFAULT 30,
    ADD COLUMN IF NOT EXISTS pacing_jitter_max_s integer DEFAULT 180,
    ADD COLUMN IF NOT EXISTS last_action_at      timestamptz;

INSERT INTO schema_migrations (version, description)
SELECT 443, 'S.I.G.N.A.L. engagement ledger + per-agent budget/pacing (S7-P1-4a)'
WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = '443');

COMMIT;
