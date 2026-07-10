-- Chronicle: track permanent attachment-fetch failures so the downloader stops retrying them.
--
-- Problem: an email with has_attachments=TRUE whose Gmail message was later DELETED returns
-- HTTP 404 on get_email. It never gets a mailbox_attachments row, so it stays a permanent
-- _candidate_emails candidate and run_attachment_download re-attempts it every cycle forever
-- (the "poison pill" spin). has_attachments must NOT be flipped — it is read for display in
-- the Chronicle reader (mailbox_story/routes.py) and was true.
--
-- Fix: a dedicated nullable marker. NULL = pending/retryable (default); 'unavailable' = the
-- Gmail message is gone (404), permanently unretrievable → excluded from candidacy.
ALTER TABLE mailbox_emails
    ADD COLUMN IF NOT EXISTS attachment_fetch_status TEXT;

-- Partial index keeps the candidate query cheap on large imports (only marks the exceptions).
CREATE INDEX IF NOT EXISTS idx_mailbox_emails_att_fetch_unavailable
    ON mailbox_emails (id)
    WHERE attachment_fetch_status = 'unavailable';
