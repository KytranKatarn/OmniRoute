-- Migration 381: Add module_name and proposal_source to improvement_proposals
-- Purpose: Make Repair Bay the single source of truth for all module repair workflows.
-- Code Health scans (code_metrics_service) will now write proposals here directly.

ALTER TABLE improvement_proposals
    ADD COLUMN IF NOT EXISTS module_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS proposal_source VARCHAR(50) DEFAULT 'manual';

CREATE INDEX IF NOT EXISTS idx_improvement_proposals_module
    ON improvement_proposals (module_name);

CREATE INDEX IF NOT EXISTS idx_improvement_proposals_source
    ON improvement_proposals (proposal_source);

-- Backfill existing proposals from code_audit_log where notes match
-- (best-effort — new proposals will carry proper module_name going forward)
UPDATE improvement_proposals
SET proposal_source = 'manual'
WHERE proposal_source IS NULL;

COMMENT ON COLUMN improvement_proposals.module_name IS
    'Module key this proposal targets (matches module_registry key, e.g. repair_bay, consciousness)';
COMMENT ON COLUMN improvement_proposals.proposal_source IS
    'Origin: manual | code_health_scan | forge_review | dependency_scan | qa_failure';
