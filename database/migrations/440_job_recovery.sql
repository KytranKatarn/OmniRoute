-- 440_job_recovery.sql
-- #1716 Durable Execution slice 1 — interrupted-job recovery for bridge_jobs.
-- Additive, nullable columns only (no table rewrite on the 542K-row hot table).
-- A new status value 'interrupted' is introduced (bridge_jobs has no status CHECK constraint).

ALTER TABLE bridge_jobs ADD COLUMN IF NOT EXISTS replay_of   INTEGER;       -- original job id this row is a replay of
ALTER TABLE bridge_jobs ADD COLUMN IF NOT EXISTS replayed_at TIMESTAMPTZ;   -- when the original was replayed
ALTER TABLE bridge_jobs ADD COLUMN IF NOT EXISTS checkpoint  JSONB;         -- recovery checkpoint (completed/total steps, reason)

-- Powers the stale-running reaper (status='running' AND updated_at < cutoff).
CREATE INDEX IF NOT EXISTS idx_bridge_jobs_status_updated ON bridge_jobs (status, updated_at);
