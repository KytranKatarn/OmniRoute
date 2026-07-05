-- 448_ab_compare_status.sql — allow 'pending_approval' status for cloud A/B comparison runs (#4661)
ALTER TABLE action_benchmark_runs DROP CONSTRAINT IF EXISTS action_benchmark_runs_status_check;
ALTER TABLE action_benchmark_runs ADD CONSTRAINT action_benchmark_runs_status_check
  CHECK (status IN ('running','completed','failed','cancelled','pending_approval'));
