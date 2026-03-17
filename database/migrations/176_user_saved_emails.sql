-- Migration 176: Per-user saved emails for SaaS Google Work Suite
-- Each user can save emails to their personal collection

CREATE TABLE IF NOT EXISTS user_saved_emails (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    gmail_id VARCHAR(100) NOT NULL,
    subject VARCHAR(500),
    sender VARCHAR(200),
    recipients JSONB DEFAULT '[]',
    body_text TEXT,
    received_at TIMESTAMP,
    ai_sentiment VARCHAR(20),
    ai_priority VARCHAR(20),
    ai_category VARCHAR(50),
    ai_summary TEXT,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    saved_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, gmail_id)
);

CREATE INDEX IF NOT EXISTS idx_user_saved_emails_user ON user_saved_emails(user_id);
CREATE INDEX IF NOT EXISTS idx_user_saved_emails_account ON user_saved_emails(account_id);
