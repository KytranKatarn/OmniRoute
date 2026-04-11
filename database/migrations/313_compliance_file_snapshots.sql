-- Compliance File Snapshots: git-style version tracking for host config changes
-- Captures file content before each fix so we can diff and rollback

CREATE TABLE IF NOT EXISTS compliance_file_snapshots (
    id SERIAL PRIMARY KEY,
    remediation_id INTEGER REFERENCES compliance_remediations(id) ON DELETE CASCADE,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
    file_path VARCHAR(500) NOT NULL,
    content_before TEXT,
    content_after TEXT,
    sha256_before VARCHAR(64),
    sha256_after VARCHAR(64),
    change_summary TEXT,
    captured_at TIMESTAMP DEFAULT NOW(),
    rolled_back_at TIMESTAMP,
    rolled_back_by INTEGER
);

CREATE INDEX IF NOT EXISTS idx_comp_snapshots_remediation
    ON compliance_file_snapshots(remediation_id);

CREATE INDEX IF NOT EXISTS idx_comp_snapshots_proposal
    ON compliance_file_snapshots(proposal_id);

CREATE INDEX IF NOT EXISTS idx_comp_snapshots_path
    ON compliance_file_snapshots(file_path);

CREATE INDEX IF NOT EXISTS idx_comp_snapshots_active
    ON compliance_file_snapshots(file_path, captured_at DESC)
    WHERE rolled_back_at IS NULL;
