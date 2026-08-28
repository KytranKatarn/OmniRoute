-- 481: per-mailbox sync-health stamps (#5849)
-- A forked/auth-broken mailbox must not render identically to a healthy one —
-- the OWNER mailbox failed IMAP auth for 9 days (08-19 -> 08-28) invisible in
-- Email HQ because sync outcomes lived only in scheduler log lines.
-- Success clears the error; failure stamps it. Idempotent.
ALTER TABLE email_mailboxes ADD COLUMN IF NOT EXISTS last_sync_ok_at timestamptz;
ALTER TABLE email_mailboxes ADD COLUMN IF NOT EXISTS last_sync_error text;
ALTER TABLE email_mailboxes ADD COLUMN IF NOT EXISTS last_sync_error_at timestamptz;
