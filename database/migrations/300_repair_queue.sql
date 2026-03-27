-- 300_repair_queue.sql
-- Repair Bay v2: repair_queue + manifest_registry tables
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS repair_queue (
    id SERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL CHECK (source IN ('dependabot', 'scan', 'coderabbit')),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    package_name VARCHAR(255),
    manifest_path VARCHAR(500),
    alert_number INTEGER,
    advisory_id VARCHAR(50),
    vulnerable_range VARCHAR(100),
    fix_version VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'fixed', 'failed', 'escalated', 'dismissed')),
    proposal_id INTEGER,
    assigned_agent VARCHAR(100),
    pr_number INTEGER,
    attempts INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    dismiss_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repair_queue_source_alert
    ON repair_queue(source, alert_number) WHERE alert_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_repair_queue_status ON repair_queue(status);
CREATE INDEX IF NOT EXISTS idx_repair_queue_severity ON repair_queue(severity);

CREATE TABLE IF NOT EXISTS manifest_registry (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL UNIQUE,
    manifest_type VARCHAR(20) NOT NULL
        CHECK (manifest_type IN ('pip', 'npm', 'go', 'ruby', 'cargo')),
    last_scanned_at TIMESTAMP,
    package_count INTEGER DEFAULT 0,
    alert_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
