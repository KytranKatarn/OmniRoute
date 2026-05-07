-- Migration 372: backup governance support
-- Adds clearance tracking to improvement_proposals + inserts severity gate config

-- Clearance columns on improvement_proposals
ALTER TABLE improvement_proposals
  ADD COLUMN IF NOT EXISTS backup_clearance_approved BOOLEAN,
  ADD COLUMN IF NOT EXISTS backup_clearance_snapshot_id INTEGER REFERENCES module_snapshots(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS backup_clearance_task_id INTEGER,
  ADD COLUMN IF NOT EXISTS backup_clearance_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS backup_clearance_reason TEXT;

-- Severity gate config
INSERT INTO system_config (key, value, description)
VALUES (
  'backup_governance_gates',
  '{"critical":{"max_age_hours":48,"gate_type":"soft","override":"none"},"high":{"max_age_hours":12,"gate_type":"soft","override":"telegram_approval"},"medium":{"max_age_hours":6,"gate_type":"hard","override":"kytran_approval"},"low":{"max_age_hours":24,"gate_type":"hard","override":"kytran_approval"}}',
  'W.A.R.D.E.N. backup governance severity gates — editable via Backup Manager Admin tab'
)
ON CONFLICT (key) DO NOTHING;
