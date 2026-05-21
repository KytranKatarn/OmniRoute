-- Migration 387: Add DEFAULT 'scheduled_job' to task_execution_log.task_type
--
-- task_type was NOT NULL with no default, silently blocking all scheduled-job
-- INSERTs in consciousness/jobs.py and department_hq/jobs.py that omit the column.
-- Adding the default lets those INSERTs succeed and makes agent work visible
-- in the ARMADA Dispatch Traffic + History panels.
--
-- Idempotent: safe to re-run.

ALTER TABLE task_execution_log
  ALTER COLUMN task_type SET DEFAULT 'scheduled_job';
