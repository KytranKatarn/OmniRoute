ALTER TABLE director_reports
  ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(64);

-- Unique constraint required for ON CONFLICT (dedup_key) DO NOTHING in briefing_service.py
-- A partial index (WHERE dedup_key IS NOT NULL) does NOT satisfy ON CONFLICT.
ALTER TABLE director_reports
  ADD CONSTRAINT IF NOT EXISTS director_reports_dedup_key_unique UNIQUE (dedup_key);
