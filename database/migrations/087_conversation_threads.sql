-- Migration 087: Create ai_conversation_threads table
-- Part of Chat Redesign Phase 1: Conversation thread tracking
-- Creates a browsable threads table and backfills from existing ai_conversations

BEGIN;

-- 1. Create the conversation threads table
CREATE TABLE IF NOT EXISTS ai_conversation_threads (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    chat_mode VARCHAR(50) DEFAULT 'solo',
    message_count INTEGER DEFAULT 0,
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Create index for efficient user-scoped queries sorted by recency
CREATE INDEX IF NOT EXISTS idx_conv_threads_user
    ON ai_conversation_threads(user_id, last_message_at DESC);

-- 3. Backfill from existing ai_conversations data
-- One row per distinct conversation_id, with:
--   title = first 80 chars of the earliest message
--   chat_mode from metadata (default 'solo')
--   message_count = total messages in that conversation
--   created_at = earliest message timestamp
--   last_message_at = latest message timestamp
INSERT INTO ai_conversation_threads (
    conversation_id,
    user_id,
    title,
    chat_mode,
    message_count,
    is_archived,
    created_at,
    updated_at,
    last_message_at
)
SELECT
    c.conversation_id,
    c.user_id,
    LEFT(first_msg.message, 80) AS title,
    COALESCE(first_msg.chat_mode, 'solo') AS chat_mode,
    c.message_count,
    FALSE AS is_archived,
    c.first_message_at AS created_at,
    c.last_message_at AS updated_at,
    c.last_message_at
FROM (
    -- Aggregate stats per conversation
    SELECT
        conversation_id,
        MIN(user_id) AS user_id,
        COUNT(*) AS message_count,
        MIN(created_at) AS first_message_at,
        MAX(created_at) AS last_message_at
    FROM ai_conversations
    WHERE conversation_id IS NOT NULL
    GROUP BY conversation_id
) c
JOIN LATERAL (
    -- Get the first message and its chat_mode for each conversation
    SELECT
        ac.message,
        ac.metadata->>'chat_mode' AS chat_mode
    FROM ai_conversations ac
    WHERE ac.conversation_id = c.conversation_id
    ORDER BY ac.created_at ASC
    LIMIT 1
) first_msg ON TRUE
ON CONFLICT (conversation_id) DO NOTHING;

COMMIT;
