-- 250_audit_pipeline_columns.sql
-- Code Health Audit Pipeline — new tracking columns
-- Adds audit profile, trigger reason, and dispatcher tracking to code_audit_log
-- Adds change detection tracking to code_metrics_snapshots

ALTER TABLE code_audit_log
    ADD COLUMN IF NOT EXISTS audit_profile VARCHAR(20) DEFAULT 'python',
    ADD COLUMN IF NOT EXISTS trigger_reason VARCHAR(30) DEFAULT 'scheduled',
    ADD COLUMN IF NOT EXISTS dispatched_via VARCHAR(50);

COMMENT ON COLUMN code_audit_log.audit_profile IS 'python, web, or config — auto-detected from module file composition';
COMMENT ON COLUMN code_audit_log.trigger_reason IS 'change_detected, manual, scheduled, stale_reaudit';
COMMENT ON COLUMN code_audit_log.dispatched_via IS 'Agent name that ran the audit (e.g. F.O.R.G.E.)';

ALTER TABLE code_metrics_snapshots
    ADD COLUMN IF NOT EXISTS modules_changed JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN code_metrics_snapshots.modules_changed IS 'List of module keys that changed vs previous snapshot';
