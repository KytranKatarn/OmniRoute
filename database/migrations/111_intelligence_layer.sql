-- Migration 111: Intelligence Layer additions
-- Phase 7: Analytics, Memory, Proactive, Export

-- Memory system enhancements
ALTER TABLE long_term_memory ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'system';
ALTER TABLE long_term_memory ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_ltm_user_active ON long_term_memory(user_id) WHERE is_deleted = FALSE;

-- Notification read tracking (is_read already exists; add read_at + partial index)
ALTER TABLE system_notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_sn_unread ON system_notifications(created_at DESC) WHERE is_read = FALSE;

-- Chat export log
CREATE TABLE IF NOT EXISTS chat_export_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    export_format TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
