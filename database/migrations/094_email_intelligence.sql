-- ============================================================================
-- Migration 094: Email Intelligence
-- Purpose: IMAP inbox management, AI-powered email analysis, draft replies
-- Created: 2026-02-17
-- ============================================================================

-- IMAP account settings
CREATE TABLE IF NOT EXISTS email_imap_settings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) DEFAULT 'Default',
    imap_host VARCHAR(255) NOT NULL,
    imap_port INTEGER DEFAULT 993,
    imap_user VARCHAR(255) NOT NULL,
    imap_password_encrypted TEXT NOT NULL,
    encryption VARCHAR(20) DEFAULT 'ssl',   -- 'ssl', 'tls', 'none'
    folder VARCHAR(100) DEFAULT 'INBOX',
    is_active BOOLEAN DEFAULT TRUE,
    last_uid INTEGER DEFAULT 0,             -- highest UID fetched so far
    last_check_at TIMESTAMP,
    check_interval_minutes INTEGER DEFAULT 5,
    auto_analyze BOOLEAN DEFAULT TRUE,      -- auto-run AI analysis on new emails
    auto_file_kb BOOLEAN DEFAULT FALSE,     -- auto-file important emails to knowledge_base
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Received email inbox
CREATE TABLE IF NOT EXISTS email_inbox (
    id SERIAL PRIMARY KEY,
    imap_setting_id INTEGER REFERENCES email_imap_settings(id),
    uid INTEGER,                            -- IMAP UID
    message_id VARCHAR(500),                -- RFC Message-ID header
    from_address VARCHAR(500) NOT NULL,
    from_name VARCHAR(500),
    to_address VARCHAR(500),
    cc_address TEXT,
    subject VARCHAR(1000),
    body_text TEXT,
    body_html TEXT,
    received_at TIMESTAMP,
    has_attachments BOOLEAN DEFAULT FALSE,
    attachment_names JSONB DEFAULT '[]',
    -- AI analysis fields
    ai_category VARCHAR(50),               -- 'urgent', 'action_required', 'informational', 'spam', 'newsletter'
    ai_summary TEXT,
    ai_sentiment VARCHAR(30),              -- 'positive', 'neutral', 'negative', 'mixed'
    ai_priority INTEGER,                   -- 1-5 (1=highest)
    ai_suggested_action TEXT,
    ai_analyzed_at TIMESTAMP,
    -- CRM link
    crm_customer_id INTEGER REFERENCES crm_customers(id),
    -- Status
    is_read BOOLEAN DEFAULT FALSE,
    is_starred BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    kb_entry_id INTEGER REFERENCES knowledge_base(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Draft email replies
CREATE TABLE IF NOT EXISTS email_drafts (
    id SERIAL PRIMARY KEY,
    inbox_email_id INTEGER REFERENCES email_inbox(id),
    to_address VARCHAR(500) NOT NULL,
    subject VARCHAR(1000),
    body_html TEXT,
    body_text TEXT,
    status VARCHAR(50) DEFAULT 'draft',    -- 'draft', 'queued', 'sent', 'discarded'
    ai_generated BOOLEAN DEFAULT TRUE,
    edited_by INTEGER REFERENCES users(id),
    approval_id INTEGER REFERENCES autonomy_approval_queue(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_imap_settings_active ON email_imap_settings(is_active);
CREATE INDEX IF NOT EXISTS idx_inbox_from ON email_inbox(from_address);
CREATE INDEX IF NOT EXISTS idx_inbox_category ON email_inbox(ai_category);
CREATE INDEX IF NOT EXISTS idx_inbox_priority ON email_inbox(ai_priority);
CREATE INDEX IF NOT EXISTS idx_inbox_received ON email_inbox(received_at);
CREATE INDEX IF NOT EXISTS idx_inbox_read ON email_inbox(is_read) WHERE is_read = FALSE;
CREATE INDEX IF NOT EXISTS idx_inbox_starred ON email_inbox(is_starred) WHERE is_starred = TRUE;
CREATE INDEX IF NOT EXISTS idx_inbox_uid ON email_inbox(imap_setting_id, uid);
CREATE INDEX IF NOT EXISTS idx_inbox_message_id ON email_inbox(message_id);
CREATE INDEX IF NOT EXISTS idx_inbox_crm ON email_inbox(crm_customer_id) WHERE crm_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_drafts_inbox ON email_drafts(inbox_email_id);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON email_drafts(status);

-- Grant permissions
GRANT ALL ON email_imap_settings TO archie;
GRANT ALL ON email_inbox TO archie;
GRANT ALL ON email_drafts TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE email_imap_settings IS 'IMAP account configuration for receiving emails';
COMMENT ON TABLE email_inbox IS 'Received emails with AI analysis (category, summary, sentiment, priority)';
COMMENT ON TABLE email_drafts IS 'AI-generated and manual draft email replies';
