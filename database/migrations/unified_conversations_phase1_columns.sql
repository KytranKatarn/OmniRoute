-- Phase 1 of the unified_conversations migration (#2173, decision doc:
-- docs/superpowers/specs/2026-04-19-conversation-data-model-decision.md).
-- Adds the product columns chat_conversations has but unified_conversations lacks.
-- Idempotent: safe to re-run.
--
-- Column diff (2026-04-19):
--   Adding:   title, agent_target, team_id, is_archived, conversation_uuid, updated_at
--   Already present in unified_conversations (not added): topic, status, last_activity
--   teams table does NOT exist → team_id is plain INTEGER with no FK

ALTER TABLE unified_conversations
    ADD COLUMN IF NOT EXISTS title           VARCHAR(255),
    ADD COLUMN IF NOT EXISTS agent_target    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS team_id         INTEGER,
    ADD COLUMN IF NOT EXISTS is_archived     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS conversation_uuid UUID DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();

-- UNIQUE constraint on conversation_uuid (idempotent via DO block)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'unified_conversations_conversation_uuid_key'
    ) THEN
        ALTER TABLE unified_conversations
            ADD CONSTRAINT unified_conversations_conversation_uuid_key
            UNIQUE (conversation_uuid);
    END IF;
END $$;

-- Backfill existing rows that got NULL conversation_uuid (DEFAULT only applies to new rows)
UPDATE unified_conversations
SET conversation_uuid = gen_random_uuid()
WHERE conversation_uuid IS NULL;

-- Backfill updated_at for existing rows (match created_at as best approximation)
UPDATE unified_conversations
SET updated_at = created_at
WHERE updated_at IS NULL;

-- Supporting indexes (mirroring chat_conversations index pattern)
CREATE INDEX IF NOT EXISTS idx_unified_conv_team
    ON unified_conversations(team_id) WHERE team_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_unified_conv_archived
    ON unified_conversations(is_archived) WHERE is_archived = FALSE;

CREATE INDEX IF NOT EXISTS idx_unified_conv_uuid
    ON unified_conversations(conversation_uuid);

CREATE INDEX IF NOT EXISTS idx_unified_conv_updated
    ON unified_conversations(updated_at DESC);
