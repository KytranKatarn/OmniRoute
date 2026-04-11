-- Scan Campaigns: group multiple scans under a client engagement
CREATE TABLE IF NOT EXISTS scan_campaigns (
    id SERIAL PRIMARY KEY,
    client_name VARCHAR(200) NOT NULL,
    target VARCHAR(500) NOT NULL,
    profile VARCHAR(50) DEFAULT 'standard',
    scanners JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'running',
    scan_ids JSONB DEFAULT '[]',
    created_by VARCHAR(50) DEFAULT 'user',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scan_campaigns_status ON scan_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_scan_campaigns_client ON scan_campaigns(client_name);

-- Add campaign_id to existing scan tables for grouping
ALTER TABLE security_recon_scans ADD COLUMN IF NOT EXISTS campaign_id INTEGER REFERENCES scan_campaigns(id) ON DELETE SET NULL;
