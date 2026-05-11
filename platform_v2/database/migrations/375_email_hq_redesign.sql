-- platform_v2/database/migrations/375_email_hq_redesign.sql

CREATE TABLE IF NOT EXISTS email_messages (
    id               SERIAL PRIMARY KEY,
    mailbox_id       INTEGER NOT NULL REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    message_id       TEXT NOT NULL,
    uid              INTEGER,
    subject          TEXT,
    from_address     TEXT,
    to_address       TEXT,
    cc_address       TEXT,
    reply_to         TEXT,
    received_at      TIMESTAMPTZ,
    body_html        TEXT,
    body_text        TEXT,
    body_preview     TEXT,
    has_attachments  BOOLEAN DEFAULT FALSE,
    attachment_names TEXT[],
    size_bytes       INTEGER,
    is_read          BOOLEAN DEFAULT FALSE,
    is_starred       BOOLEAN DEFAULT FALSE,
    is_archived      BOOLEAN DEFAULT FALSE,
    ai_priority      TEXT CHECK (ai_priority IN ('action', 'review', 'info')),
    ai_suggestion    TEXT,
    ai_agent_id      INTEGER REFERENCES agents(id),
    ai_triaged_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mailbox_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_email_messages_mailbox
    ON email_messages(mailbox_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_messages_unread
    ON email_messages(mailbox_id, is_read) WHERE is_read = FALSE;
CREATE INDEX IF NOT EXISTS idx_email_messages_priority
    ON email_messages(ai_priority) WHERE ai_priority IS NOT NULL;

ALTER TABLE email_mailboxes
    DROP CONSTRAINT IF EXISTS email_mailboxes_mailbox_type_check;
ALTER TABLE email_mailboxes
    ADD CONSTRAINT email_mailboxes_mailbox_type_check
    CHECK (mailbox_type IN ('ai_agent', 'business', 'owner'));
