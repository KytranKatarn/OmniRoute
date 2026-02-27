-- Migration 125: Notification Visibility + Per-User Read Tracking
-- Adds visibility scoping so regular users only see relevant notifications
-- Adds per-user read tracking (replacing global is_read flag)

BEGIN;

-- 1. Add visibility column to system_notifications
ALTER TABLE system_notifications
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(10) NOT NULL DEFAULT 'all';

-- Add check constraint for visibility values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'system_notifications_visibility_check'
    ) THEN
        ALTER TABLE system_notifications
            ADD CONSTRAINT system_notifications_visibility_check
            CHECK (visibility IN ('all', 'admin', 'user'));
    END IF;
END $$;

-- 2. Add target_user_id column (nullable FK for user-specific notifications)
ALTER TABLE system_notifications
    ADD COLUMN IF NOT EXISTS target_user_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'system_notifications_target_user_fk'
    ) THEN
        ALTER TABLE system_notifications
            ADD CONSTRAINT system_notifications_target_user_fk
            FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

-- 3. Create notification_reads junction table for per-user read tracking
CREATE TABLE IF NOT EXISTS notification_reads (
    id SERIAL PRIMARY KEY,
    notification_id INTEGER NOT NULL REFERENCES system_notifications(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(notification_id, user_id)
);

-- 4. Add indexes
CREATE INDEX IF NOT EXISTS idx_sn_visibility ON system_notifications(visibility);
CREATE INDEX IF NOT EXISTS idx_sn_target_user ON system_notifications(target_user_id);
CREATE INDEX IF NOT EXISTS idx_nr_user_notif ON notification_reads(user_id, notification_id);
CREATE INDEX IF NOT EXISTS idx_nr_notif ON notification_reads(notification_id);

-- 5. Backfill: migrate existing is_read=TRUE rows into notification_reads for Kytran (user_id=2)
INSERT INTO notification_reads (notification_id, user_id, read_at)
SELECT id, 2, COALESCE(read_at, NOW())
FROM system_notifications
WHERE is_read = TRUE
ON CONFLICT (notification_id, user_id) DO NOTHING;

-- 6. Backfill: set visibility='admin' for existing admin-only notification sources
UPDATE system_notifications
SET visibility = 'admin'
WHERE source IN ('github_deploy', 'security_monitor')
  AND visibility = 'all';

-- Note: is_read column kept intact (deprecated, not dropped) for backward safety

COMMIT;
