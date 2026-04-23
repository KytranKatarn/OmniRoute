ALTER TABLE director_reports
  ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_director_reports_dedup
  ON director_reports(dedup_key)
  WHERE dedup_key IS NOT NULL;
