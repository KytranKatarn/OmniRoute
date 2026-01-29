-- Migration: 038_backup_webhooks
-- Description: Create backup_webhooks table for webhook notifications
-- Date: 2026-01-29

-- Backup webhooks table for notification on backup events
CREATE TABLE IF NOT EXISTS backup_webhooks (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    event_types TEXT[] DEFAULT ARRAY['backup_complete', 'backup_failed'],
    active BOOLEAN DEFAULT TRUE,
    secret_key TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_triggered TIMESTAMP,
    last_status INTEGER
);

-- Index for active webhooks
CREATE INDEX IF NOT EXISTS idx_backup_webhooks_active ON backup_webhooks(active);

-- Comment
COMMENT ON TABLE backup_webhooks IS 'Webhook endpoints for backup event notifications';
COMMENT ON COLUMN backup_webhooks.event_types IS 'Array of event types: backup_complete, backup_failed';
COMMENT ON COLUMN backup_webhooks.secret_key IS 'HMAC secret for X-Archie-Signature header';
