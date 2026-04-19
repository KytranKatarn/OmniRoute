-- Audit columns for multi-source approvals UI (spec 2026-04-19-dhq-approvals-multi-source-design).
-- Idempotent: safe to run multiple times.

-- contractor_approval_requests: add denied_by + denied_at so web deny can mirror autonomy audit shape.
ALTER TABLE contractor_approval_requests
    ADD COLUMN IF NOT EXISTS denied_by INTEGER,
    ADD COLUMN IF NOT EXISTS denied_at TIMESTAMP WITHOUT TIME ZONE;

-- bridge_jobs: add approval + cancellation audit columns.
ALTER TABLE bridge_jobs
    ADD COLUMN IF NOT EXISTS approved_by INTEGER,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS cancelled_by INTEGER,
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;
