-- Migration 378: email_threads table + thread_id/in_reply_to/references_header on email_messages
-- Applied directly via psql in this session (2026-05-10)

BEGIN;

CREATE TABLE IF NOT EXISTS email_threads (
    id              SERIAL PRIMARY KEY,
    mailbox_id      INTEGER NOT NULL REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    subject         TEXT,
    message_count   INTEGER NOT NULL DEFAULT 1,
    last_message_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='email_messages' AND column_name='thread_id') THEN
        ALTER TABLE email_messages ADD COLUMN thread_id INTEGER REFERENCES email_threads(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='email_messages' AND column_name='in_reply_to') THEN
        ALTER TABLE email_messages ADD COLUMN in_reply_to TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='email_messages' AND column_name='references_header') THEN
        ALTER TABLE email_messages ADD COLUMN references_header TEXT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_email_threads_mailbox ON email_threads(mailbox_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_messages_thread ON email_messages(thread_id) WHERE thread_id IS NOT NULL;

COMMIT;
