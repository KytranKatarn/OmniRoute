-- Compliance Module Tables
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/platform_v2/database/migrations/compliance_tables.sql

CREATE TABLE IF NOT EXISTS compliance_rule_packs (
    id SERIAL PRIMARY KEY,
    pack_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    version VARCHAR(20),
    source VARCHAR(50) DEFAULT 'DISA',
    total_rules INTEGER DEFAULT 0,
    rules JSONB NOT NULL,
    loaded_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_scans (
    id SERIAL PRIMARY KEY,
    scan_id UUID UNIQUE NOT NULL,
    pack_ids TEXT[] NOT NULL,
    total_rules INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    not_applicable INTEGER DEFAULT 0,
    manual INTEGER DEFAULT 0,
    score DECIMAL(5,2),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    triggered_by VARCHAR(100),
    node_id VARCHAR(64) DEFAULT 'hub'
);

CREATE TABLE IF NOT EXISTS compliance_scan_results (
    id SERIAL PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES compliance_scans(scan_id),
    pack_id VARCHAR(100) NOT NULL,
    rule_id VARCHAR(50) NOT NULL,
    severity VARCHAR(20),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pass', 'fail', 'error', 'not_applicable', 'manual')),
    actual_value TEXT,
    expected_value TEXT,
    details TEXT,
    soc2_controls TEXT[],
    scanned_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_evidence (
    id SERIAL PRIMARY KEY,
    control_id VARCHAR(20) NOT NULL,
    artifact_type VARCHAR(50) NOT NULL,
    artifact_name VARCHAR(200),
    artifact_data JSONB,
    file_path TEXT,
    collected_at TIMESTAMP DEFAULT NOW(),
    valid_until TIMESTAMP,
    scan_id UUID REFERENCES compliance_scans(scan_id)
);

CREATE TABLE IF NOT EXISTS compliance_attestations (
    id SERIAL PRIMARY KEY,
    control_id VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL CHECK (category IN ('security', 'availability', 'processing_integrity', 'confidentiality', 'privacy')),
    attested_by INTEGER REFERENCES users(id),
    status VARCHAR(20) NOT NULL CHECK (status IN ('compliant', 'non_compliant', 'not_applicable', 'in_progress')),
    notes TEXT,
    evidence_url TEXT,
    attested_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS compliance_remediations (
    id SERIAL PRIMARY KEY,
    scan_id UUID REFERENCES compliance_scans(scan_id),
    rule_id VARCHAR(50) NOT NULL,
    pack_id VARCHAR(100),
    action_type VARCHAR(50),
    command_executed TEXT,
    result VARCHAR(20) CHECK (result IN ('success', 'failed', 'pending', 'cancelled')),
    risk_level VARCHAR(20),
    executed_by INTEGER REFERENCES users(id),
    confirmed_at TIMESTAMP,
    executed_at TIMESTAMP DEFAULT NOW(),
    before_value TEXT,
    after_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON compliance_scan_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_results_status ON compliance_scan_results(status);
CREATE INDEX IF NOT EXISTS idx_scan_results_severity ON compliance_scan_results(severity);
CREATE INDEX IF NOT EXISTS idx_scans_completed ON compliance_scans(completed_at);
CREATE INDEX IF NOT EXISTS idx_evidence_control ON compliance_evidence(control_id);
CREATE INDEX IF NOT EXISTS idx_remediations_scan ON compliance_remediations(scan_id);
