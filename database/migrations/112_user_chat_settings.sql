-- Migration 112: User chat settings
-- Phase 8: Settings, Search & Mobile

CREATE TABLE IF NOT EXISTS user_chat_settings (
    user_id INTEGER PRIMARY KEY,
    settings JSONB DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE user_chat_settings IS 'Per-user chat UI preferences (theme, font size, default mode, etc.)';
