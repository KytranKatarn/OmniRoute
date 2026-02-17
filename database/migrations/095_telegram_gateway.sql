-- ============================================================================
-- Migration 095: Telegram Gateway
-- Purpose: Telegram bot user linking, message logging, notification rules
-- Created: 2026-02-17
-- ============================================================================

-- Telegram user accounts linked to platform users
CREATE TABLE IF NOT EXISTS telegram_users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,     -- Telegram user ID
    telegram_username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    user_id INTEGER REFERENCES users(id),   -- linked ARCHIE user
    is_authorized BOOLEAN DEFAULT FALSE,    -- must be explicitly authorized
    link_code VARCHAR(20),                  -- one-time code for linking
    link_code_expires_at TIMESTAMP,
    voice_enabled BOOLEAN DEFAULT TRUE,     -- receive/send voice messages
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Telegram message log
CREATE TABLE IF NOT EXISTS telegram_messages (
    id SERIAL PRIMARY KEY,
    telegram_user_id INTEGER REFERENCES telegram_users(id),
    direction VARCHAR(10) NOT NULL DEFAULT 'in', -- 'in' (from user) or 'out' (from ARCHIE)
    message_type VARCHAR(30) DEFAULT 'text',     -- 'text', 'voice', 'command', 'callback', 'photo'
    content TEXT,
    orchestration_session_id VARCHAR(100),        -- links to orchestration if routed
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Notification forwarding rules
CREATE TABLE IF NOT EXISTS telegram_notification_rules (
    id SERIAL PRIMARY KEY,
    telegram_user_id INTEGER REFERENCES telegram_users(id),
    notification_type VARCHAR(50),           -- null = all types, or specific like 'reminder', 'error', 'info'
    priority_min VARCHAR(20) DEFAULT 'normal', -- minimum priority to forward: 'low', 'normal', 'high', 'critical'
    source_filter VARCHAR(100),              -- null = all sources, or specific like 'agent_loop'
    is_active BOOLEAN DEFAULT TRUE,
    quiet_hours_start TIME,                  -- optional quiet hours (no forwarding)
    quiet_hours_end TIME,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Track which notifications have been forwarded to avoid duplicates
ALTER TABLE system_notifications
    ADD COLUMN IF NOT EXISTS telegram_forwarded BOOLEAN DEFAULT FALSE;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_telegram_users_tgid ON telegram_users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_telegram_users_link ON telegram_users(link_code) WHERE link_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_telegram_users_user ON telegram_users(user_id);
CREATE INDEX IF NOT EXISTS idx_telegram_messages_user ON telegram_messages(telegram_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_telegram_messages_dir ON telegram_messages(direction, created_at);
CREATE INDEX IF NOT EXISTS idx_telegram_rules_user ON telegram_notification_rules(telegram_user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_notifications_tg_fwd ON system_notifications(telegram_forwarded) WHERE telegram_forwarded = FALSE;

-- Default notification rules for first linked user (catch-all)
-- Will be populated when user links their account

-- Grant permissions
GRANT ALL ON telegram_users TO archie;
GRANT ALL ON telegram_messages TO archie;
GRANT ALL ON telegram_notification_rules TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE telegram_users IS 'Telegram accounts linked to platform users';
COMMENT ON TABLE telegram_messages IS 'Log of all Telegram bot messages (in and out)';
COMMENT ON TABLE telegram_notification_rules IS 'Rules for forwarding system notifications to Telegram';
