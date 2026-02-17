-- Email threading support
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS in_reply_to TEXT;
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS references_header TEXT;
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS thread_id TEXT;

-- Index for thread lookups
CREATE INDEX IF NOT EXISTS idx_email_thread_id ON email_inbox(thread_id) WHERE thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_email_message_id ON email_inbox(message_id) WHERE message_id IS NOT NULL;

-- Backfill: each existing email without thread_id gets its own message_id as thread_id
UPDATE email_inbox SET thread_id = message_id WHERE thread_id IS NULL AND message_id IS NOT NULL;
