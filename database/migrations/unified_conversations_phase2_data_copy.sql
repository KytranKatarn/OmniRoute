-- Phase 2 data copy: chat_conversations → unified_conversations (#2174).
-- Idempotent via conversation_uuid match.

INSERT INTO unified_conversations
    (user_id, topic, status, created_at, last_activity, updated_at,
     title, agent_target, team_id, is_archived, conversation_uuid)
SELECT
    c.user_id,
    COALESCE(c.title, 'Untitled'),         -- unified.topic is the legacy display column
    CASE WHEN c.is_archived THEN 'archived' ELSE 'active' END,
    c.created_at,
    c.updated_at,
    c.updated_at,
    c.title,
    c.agent_target,
    c.team_id,
    c.is_archived,
    c.conversation_uuid
FROM chat_conversations c
WHERE NOT EXISTS (
    SELECT 1 FROM unified_conversations u
    WHERE u.conversation_uuid = c.conversation_uuid
);

-- Copy chat_messages → unified_messages (idempotent via conversation_uuid mapping).
INSERT INTO unified_messages
    (conversation_id, channel, direction, sender, content, metadata, created_at)
SELECT
    u.id AS conversation_id,
    'web' AS channel,
    CASE WHEN m.role = 'user' THEN 'inbound' ELSE 'outbound' END AS direction,
    CASE WHEN m.role = 'user' THEN 'user' ELSE COALESCE(m.agent_used, 'assistant') END AS sender,
    m.content,
    jsonb_build_object(
        'role', m.role,
        'agent_used', m.agent_used,
        'model_used', m.model_used,
        'station_code', m.station_code,
        'duration_ms', m.duration_ms,
        'token_count', m.token_count
    ) AS metadata,
    m.created_at
FROM chat_messages m
JOIN chat_conversations c ON c.id = m.conversation_id
JOIN unified_conversations u ON u.conversation_uuid = c.conversation_uuid
WHERE NOT EXISTS (
    -- Dedup: skip if a unified_messages row already exists for the same
    -- (unified conversation, created_at, content) tuple.
    SELECT 1 FROM unified_messages um
    WHERE um.conversation_id = u.id
      AND um.created_at = m.created_at
      AND um.content = m.content
);
