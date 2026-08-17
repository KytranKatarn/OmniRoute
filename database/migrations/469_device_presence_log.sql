-- 469_device_presence_log.sql
-- Security & Network: presence-tracking table for device online/offline events.
--
-- WHY: device_presence_log was created ad-hoc directly in the live DB and never
-- captured in a migration. It backs GET /api/devices/presence/<ip> and the
-- presence job (jobs.py ~L1254-1302). On a fresh install the table is absent, so
-- presence tracking fails silently (Full Security Review, project #392, KB #289778).
--
-- Idempotent: mirrors the live schema exactly (verified via \d device_presence_log
-- 2026-08-16) so applying it against the existing hub is a no-op.

CREATE TABLE IF NOT EXISTS device_presence_log (
    id          SERIAL PRIMARY KEY,
    device_ip   VARCHAR(45) NOT NULL,
    device_mac  VARCHAR(17),
    event_type  VARCHAR(20) NOT NULL,
    detected_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_presence_device ON device_presence_log (device_ip);
CREATE INDEX IF NOT EXISTS idx_presence_time ON device_presence_log (detected_at);
