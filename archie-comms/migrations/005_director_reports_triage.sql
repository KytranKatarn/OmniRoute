-- Migration 005: triage workflow columns for director_reports
ALTER TABLE director_reports
  ADD COLUMN IF NOT EXISTS triage_status   VARCHAR(20) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS triage_action   VARCHAR(20),
  ADD COLUMN IF NOT EXISTS triage_reason   TEXT,
  ADD COLUMN IF NOT EXISTS triaged_at      TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_director_reports_pending
  ON director_reports(triage_status)
  WHERE triage_status = 'pending';
