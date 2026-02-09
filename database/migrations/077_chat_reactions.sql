-- Migration 077: Chat reactions (thumbs up/down on ARCHIE messages)
CREATE TABLE IF NOT EXISTS chat_reactions (
    id SERIAL PRIMARY KEY,
    message_id INTEGER REFERENCES ai_conversations(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    reaction VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(message_id, user_id, reaction)
);
CREATE INDEX IF NOT EXISTS idx_chat_reactions_message ON chat_reactions(message_id);
