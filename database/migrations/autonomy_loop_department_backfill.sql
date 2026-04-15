-- Migration: Add department index + backfill autonomy_loop_log
-- Date: 2026-04-14
-- Task: Phase 2B — department column already exists, add index and backfill NULLs

-- 1. Ensure column exists (idempotent)
ALTER TABLE autonomy_loop_log ADD COLUMN IF NOT EXISTS department VARCHAR(100);

-- 2. Add index for department filtering
CREATE INDEX IF NOT EXISTS idx_autonomy_loop_department ON autonomy_loop_log (department);

-- 3. Backfill NULL rows using known job-to-department mappings
-- HR / Human Resources & Culture
UPDATE autonomy_loop_log SET department = 'Human Resources & Culture'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('hr_tracker', 'training_tick', 'welfare_recovery', 'crew_wellness_tick', 'performance_rankings');

-- Security & Compliance
UPDATE autonomy_loop_log SET department = 'Security & Compliance'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('ethics_monitoring', 'compliance_scan', 'weekly_dependency_scan');

-- Customer Success & Support (communications)
UPDATE autonomy_loop_log SET department = 'Customer Success & Support'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('email_queue', 'email_inbox', 'email_telegram_notify', 'email_auto_analyze',
                   'telegram_notifications', 'reminders');

-- Executive Office
UPDATE autonomy_loop_log SET department = 'Executive Office'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('approvals', 'briefings');

-- Operations & Infrastructure
UPDATE autonomy_loop_log SET department = 'Operations & Infrastructure'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('scheduled_tasks', 'browser_tasks', 'health_probe', 'ollama_model_health',
                   'batch_medium_issues');

-- Engineering & Technology
UPDATE autonomy_loop_log SET department = 'Engineering & Technology'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('code_health_scan', 'code_health_digest', 'proactive_scan');

-- Research & Development
UPDATE autonomy_loop_log SET department = 'Research & Development'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('auto_log_ingestion', 'anomaly_detection', 'skill_analyzer');

-- Documentation & Knowledge
UPDATE autonomy_loop_log SET department = 'Documentation & Knowledge'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('skill_sync', 'github_auto_pull');

-- Analytics & Intelligence
UPDATE autonomy_loop_log SET department = 'Analytics & Intelligence'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('reports');

-- Creative & Design
UPDATE autonomy_loop_log SET department = 'Creative & Design'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('media_queue_cleanup', 'media_export_cleanup');

-- Fleet & Infrastructure
UPDATE autonomy_loop_log SET department = 'Fleet & Infrastructure'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('fleet_health_check', 'model_state_save');

-- Marketing & Communications
UPDATE autonomy_loop_log SET department = 'Marketing & Communications'
WHERE (department IS NULL OR department = '')
  AND job_name IN ('daily_code_health_digest');

-- Catch-all for test/unknown jobs
UPDATE autonomy_loop_log SET department = 'UNKNOWN'
WHERE department IS NULL OR department = '';
