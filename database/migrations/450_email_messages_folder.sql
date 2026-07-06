-- 450_email_messages_folder.sql
-- #4519: multi-folder IMAP sync (Junk + configurable folders beyond INBOX).
-- Attribute each message to its source IMAP folder so the sync can cover more than
-- INBOX with folder-aware UID-skip dedup (IMAP UIDs are per-folder — INBOX UID 5 is
-- a different message than Junk UID 5). Existing rows were all synced from INBOX, so
-- the default backfills them correctly. Row-level dedup stays keyed on the globally
-- unique (mailbox_id, message_id), so a message present in two folders is stored once.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS folder VARCHAR(255) NOT NULL DEFAULT 'INBOX';

-- Supports get_synced_uids(mailbox_id, folder) — the folder-aware UID-skip lookup.
CREATE INDEX IF NOT EXISTS idx_email_messages_mailbox_folder ON email_messages (mailbox_id, folder);
