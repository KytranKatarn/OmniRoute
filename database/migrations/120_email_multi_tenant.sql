-- Migration 120: Multi-tenant email — add user_id to email_imap_settings
-- Date: 2026-02-27
-- Purpose: Each user owns their own email accounts; notifications scoped per user

-- 1. Add user_id column (idempotent)
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
UPDATE email_imap_settings SET user_id = 2 WHERE user_id IS NULL;
ALTER TABLE email_imap_settings ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE email_imap_settings ALTER COLUMN user_id SET DEFAULT 2;
CREATE INDEX IF NOT EXISTS idx_imap_settings_user ON email_imap_settings(user_id);

-- 2. Reclassify existing email/anomaly/bridge notifications to admin-only
UPDATE system_notifications SET visibility = 'admin'
WHERE source IN ('email_intelligence', 'anomaly_detector', 'bridge_dispatcher')
  AND visibility = 'all';
