-- S.H.I.E.L.D. AI compliance analysis results
CREATE TABLE IF NOT EXISTS compliance_ai_analysis (
    id SERIAL PRIMARY KEY,
    scan_target VARCHAR(256) NOT NULL,
    scan_id INTEGER,
    executive_summary TEXT,
    remediation_plan TEXT,
    trend_analysis TEXT,
    model_used VARCHAR(64),
    tokens_used INTEGER,
    generated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_target ON compliance_ai_analysis(scan_target);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_scan ON compliance_ai_analysis(scan_id);
