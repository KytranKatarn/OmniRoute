-- Compliance Fix Pipeline: add stage tracking for AI review → dry-run → apply → verify
-- Idempotent: uses IF NOT EXISTS for all adds

ALTER TABLE compliance_remediations
    ADD COLUMN IF NOT EXISTS proposal_id INTEGER REFERENCES improvement_proposals(id),
    ADD COLUMN IF NOT EXISTS review_result JSONB,
    ADD COLUMN IF NOT EXISTS dry_run_result JSONB,
    ADD COLUMN IF NOT EXISTS verification_result JSONB,
    ADD COLUMN IF NOT EXISTS stage VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_comp_remediations_proposal
    ON compliance_remediations(proposal_id);

CREATE INDEX IF NOT EXISTS idx_comp_remediations_stage
    ON compliance_remediations(stage) WHERE stage IS NOT NULL;
