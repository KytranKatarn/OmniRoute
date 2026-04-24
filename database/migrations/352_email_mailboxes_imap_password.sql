-- Migration 352: Add imap_password to email_mailboxes for per-mailbox IMAP sync credentials
-- These are the Stalwart-provisioned SMTP/IMAP passwords stored encrypted for the sync job.

ALTER TABLE email_mailboxes
    ADD COLUMN IF NOT EXISTS imap_password TEXT;

COMMENT ON COLUMN email_mailboxes.imap_password IS
    'Fernet-encrypted Stalwart IMAP/SMTP password set at provision time. Used by email_imap_sync job.';
