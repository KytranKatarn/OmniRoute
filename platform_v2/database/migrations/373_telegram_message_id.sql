-- 373_telegram_message_id.sql
-- Add telegram_message_id to autonomy_approval_queue so the SIGNAL Calendar
-- modal can deep-link from a post chip back to the original Telegram message.
--
-- Spec: docs/superpowers/specs/2026-05-04-signal-calendar-living-dashboard-design.md
-- Plan: docs/superpowers/plans/2026-05-04-signal-calendar-living-dashboard-phase1.md

BEGIN;

ALTER TABLE autonomy_approval_queue
    ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_aaq_telegram_message
    ON autonomy_approval_queue(telegram_message_id)
    WHERE telegram_message_id IS NOT NULL;

COMMIT;
