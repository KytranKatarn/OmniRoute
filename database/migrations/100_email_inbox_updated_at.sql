-- Migration 100: Add missing updated_at column to email_inbox
-- The column was omitted from migration 094 but is required by
-- toggle_read, archive_email, and other imap_routes endpoints.

ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- Backfill existing rows
UPDATE email_inbox SET updated_at = created_at WHERE updated_at IS NULL;
