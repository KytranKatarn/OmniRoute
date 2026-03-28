-- Communications plugin tables — run inside tenant schema (no tenant_id column needed).
-- Call records remain in kbs_call_center. This migration adds SMS, chat, and campaigns.
-- All statements are idempotent.

-- ----------------------------------------------------------------
-- SMS Messages
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sms_messages (
    id              SERIAL PRIMARY KEY,
    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    phone_number    VARCHAR(20) NOT NULL,
    customer_id     INTEGER,
    message         TEXT NOT NULL,
    status          VARCHAR(20) DEFAULT 'queued'
                        CHECK (status IN ('queued', 'sent', 'delivered', 'failed', 'received')),
    provider        VARCHAR(20) DEFAULT 'ringcentral'
                        CHECK (provider IN ('ringcentral', 'twilio')),
    external_id     VARCHAR(255),
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sms_messages_customer_id  ON sms_messages (customer_id);
CREATE INDEX IF NOT EXISTS idx_sms_messages_phone_number ON sms_messages (phone_number);
CREATE INDEX IF NOT EXISTS idx_sms_messages_status       ON sms_messages (status);
CREATE INDEX IF NOT EXISTS idx_sms_messages_created_at   ON sms_messages (created_at);

-- ----------------------------------------------------------------
-- Chat Conversations
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_conversations (
    id              SERIAL PRIMARY KEY,
    visitor_name    VARCHAR(255),
    visitor_email   VARCHAR(255),
    customer_id     INTEGER,
    status          VARCHAR(20) DEFAULT 'active'
                        CHECK (status IN ('active', 'closed', 'archived')),
    channel         VARCHAR(20) DEFAULT 'widget'
                        CHECK (channel IN ('widget', 'internal')),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    closed_at       TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_status     ON chat_conversations (status);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_customer_id ON chat_conversations (customer_id);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_created_at ON chat_conversations (created_at);

-- ----------------------------------------------------------------
-- Chat Messages
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    sender_type     VARCHAR(10) NOT NULL CHECK (sender_type IN ('visitor', 'agent', 'system')),
    sender_name     VARCHAR(255),
    content         TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id ON chat_messages (conversation_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at      ON chat_messages (created_at);

-- ----------------------------------------------------------------
-- Email Campaigns
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_campaigns (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    subject         VARCHAR(500) NOT NULL,
    html_content    TEXT,
    text_content    TEXT,
    segment_id      INTEGER,
    status          VARCHAR(20) DEFAULT 'draft'
                        CHECK (status IN ('draft', 'scheduled', 'sending', 'sent', 'cancelled')),
    scheduled_at    TIMESTAMP,
    sent_at         TIMESTAMP,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_campaigns_status     ON email_campaigns (status);
CREATE INDEX IF NOT EXISTS idx_email_campaigns_created_at ON email_campaigns (created_at);

-- ----------------------------------------------------------------
-- Email Campaign Stats
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_campaign_stats (
    id              SERIAL PRIMARY KEY,
    campaign_id     INTEGER NOT NULL REFERENCES email_campaigns(id) ON DELETE CASCADE,
    total_sent      INTEGER DEFAULT 0,
    delivered       INTEGER DEFAULT 0,
    opened          INTEGER DEFAULT 0,
    clicked         INTEGER DEFAULT 0,
    bounced         INTEGER DEFAULT 0,
    unsubscribed    INTEGER DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_campaign_stats_campaign_id
    ON email_campaign_stats (campaign_id);
