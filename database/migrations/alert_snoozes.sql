-- alert_snoozes — durable per-alert-key suppression for interactive watchdog/HR Telegram alerts.
-- Backs the "🔕 Snooze 24h" button on operational alerts (disk pressure, queue zombie reaper,
-- HR counter drift). A key is snoozed when a row exists with snoozed_until > NOW(); send_alert()
-- (services/alert_actions_service.py) skips a send while snoozed. Idempotent.
--
-- alert_key examples: 'disk_primary', 'disk_usb', 'zombie_reaper', 'hr_<agent_alerts.id>'.
-- This is a hub `archie` DB table (NOT wtf). No DELETE grant needed — snoozes expire by time.

CREATE TABLE IF NOT EXISTS alert_snoozes (
    alert_key      TEXT PRIMARY KEY,
    snoozed_until  TIMESTAMPTZ NOT NULL,
    created_by     TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast "is this key currently snoozed?" lookups.
CREATE INDEX IF NOT EXISTS idx_alert_snoozes_until ON alert_snoozes (snoozed_until);
