-- Migration: 170_directory_chat.sql
-- Directory chat system tables + agent email/hierarchy columns

BEGIN;

-- Agent email addresses
ALTER TABLE agents ADD COLUMN IF NOT EXISTS email VARCHAR(255);

-- Org chart hierarchy
ALTER TABLE agents ADD COLUMN IF NOT EXISTS reports_to_agent_id INTEGER REFERENCES agents(id);

-- Populate emails from display_name
UPDATE agents SET email = LOWER(
  CASE
    WHEN display_name LIKE '% %' THEN
      REPLACE(LOWER(display_name), ' ', '.') || '@kytranempowerment.com'
    ELSE
      LOWER(COALESCE(display_name, name)) || '@kytranempowerment.com'
  END
) WHERE email IS NULL OR email = '';

-- Conversation threads (one per agent-user pair)
CREATE TABLE IF NOT EXISTS directory_conversations (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER NOT NULL REFERENCES agents(id),
  user_id INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  message_count INTEGER DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  UNIQUE(agent_id, user_id)
);

-- Individual messages
CREATE TABLE IF NOT EXISTS directory_messages (
  id SERIAL PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES directory_conversations(id) ON DELETE CASCADE,
  sender_type VARCHAR(10) NOT NULL CHECK (sender_type IN ('user', 'agent')),
  message TEXT NOT NULL,
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  is_pinned BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_directory_messages_conversation
  ON directory_messages(conversation_id, timestamp DESC);

-- Agent memories about users (summaries + pinned facts)
CREATE TABLE IF NOT EXISTS directory_agent_memories (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER NOT NULL REFERENCES agents(id),
  user_id INTEGER NOT NULL,
  memory_type VARCHAR(20) NOT NULL CHECK (memory_type IN ('summary', 'pinned')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_directory_agent_memories_lookup
  ON directory_agent_memories(agent_id, user_id, memory_type);

COMMIT;
