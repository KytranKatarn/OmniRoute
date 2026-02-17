-- Migration 099: Telegram Email Notifications
-- Track which emails have been notified via Telegram + per-user notification preferences

-- Track which emails have been notified via Telegram
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS telegram_notified_at TIMESTAMP;

-- Email notification preferences per Telegram user
CREATE TABLE IF NOT EXISTS telegram_email_prefs (
    id SERIAL PRIMARY KEY,
    telegram_user_id INTEGER REFERENCES telegram_users(id),
    notify_urgent BOOLEAN DEFAULT TRUE,
    notify_action_required BOOLEAN DEFAULT TRUE,
    notify_informational BOOLEAN DEFAULT FALSE,
    notify_newsletter BOOLEAN DEFAULT FALSE,
    notify_spam BOOLEAN DEFAULT FALSE,
    digest_enabled BOOLEAN DEFAULT TRUE,
    digest_interval_minutes INTEGER DEFAULT 60,
    last_digest_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tep_telegram_user UNIQUE (telegram_user_id)
);
