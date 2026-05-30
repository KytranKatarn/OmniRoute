-- 397_tel_module_source_default.sql
-- Fix "unknown" dispatch sources in the A.R.M.A.D.A. traffic-by-source panel (#3525).
--
-- Root cause: the 35 scheduled-job loggers in tools/department_hq/jobs.py and
-- tools/consciousness/jobs.py INSERT into task_execution_log with an explicit
-- column list that OMITS module_source, so it landed NULL. The panel does
-- COALESCE(module_source,'unknown'), collapsing every internal scheduled job
-- (knowledge_analysis, workforce_planning, welfare_monitoring, embedding, …)
-- into a single useless "unknown" bucket. 100% of NULL-source rows are
-- task_type='scheduled_job' — confirmed against live data 2026-05-30.
--
-- Fix: give module_source a DB default of 'agent_loop' (the system that runs
-- these scheduled jobs), so every current and future insert that omits the
-- column is correctly attributed. Then backfill the historical NULL rows.
-- Idempotent: re-running is a no-op.

ALTER TABLE task_execution_log
    ALTER COLUMN module_source SET DEFAULT 'agent_loop';

UPDATE task_execution_log
SET module_source = 'agent_loop'
WHERE module_source IS NULL;

-- Historical rows written before the 2026-05-29 dispatcher fallback
-- (department_dispatcher.py:3545, which now maps capability -> module_source
-- when no module_id is tagged) still carry the literal 'unknown'. They have a
-- valid capability, so attribute them by it — matching what live dispatch now
-- does — instead of leaving them in the "unknown" bucket.
UPDATE task_execution_log
SET module_source = capability
WHERE module_source = 'unknown'
  AND capability IS NOT NULL
  AND capability <> '';
