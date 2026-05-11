-- Migration 376: align existing email_messages table with Email HQ redesign schema
-- The table was created by a prior migration with uid (not imap_uid) and
-- missing attachment_count. This migration brings it in sync non-destructively.

BEGIN;

-- Rename uid → imap_uid (only if uid exists and imap_uid does not)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_messages' AND column_name = 'uid'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_messages' AND column_name = 'imap_uid'
    ) THEN
        ALTER TABLE email_messages RENAME COLUMN uid TO imap_uid;
    END IF;
END $$;

-- Add attachment_count if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_messages' AND column_name = 'attachment_count'
    ) THEN
        ALTER TABLE email_messages ADD COLUMN attachment_count integer DEFAULT 0;
    END IF;
END $$;

-- Ensure indexes exist (idempotent)
CREATE INDEX IF NOT EXISTS idx_email_messages_mailbox_received
    ON email_messages(mailbox_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_email_messages_unread
    ON email_messages(mailbox_id, is_read)
    WHERE is_read = FALSE;

CREATE INDEX IF NOT EXISTS idx_email_messages_priority
    ON email_messages(mailbox_id, ai_priority)
    WHERE ai_priority IS NOT NULL;

COMMIT;
