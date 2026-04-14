-- 154_unified_alert_reads.sql
-- Per-user read tracking for unified alert system (Project #251)

CREATE TABLE IF NOT EXISTS unified_alert_reads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alert_key VARCHAR(64) NOT NULL,
    read_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, alert_key)
);

CREATE INDEX IF NOT EXISTS idx_uar_user ON unified_alert_reads(user_id);
CREATE INDEX IF NOT EXISTS idx_uar_key ON unified_alert_reads(alert_key);
