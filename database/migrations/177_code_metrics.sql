-- Migration 177: Code metrics tracking for platform audit
-- Stores periodic snapshots of codebase stats + audit progress

CREATE TABLE IF NOT EXISTS code_metrics_snapshots (
    id SERIAL PRIMARY KEY,
    total_files INTEGER NOT NULL DEFAULT 0,
    total_lines INTEGER NOT NULL DEFAULT 0,
    total_folders INTEGER NOT NULL DEFAULT 0,
    python_files INTEGER NOT NULL DEFAULT 0,
    python_lines INTEGER NOT NULL DEFAULT 0,
    js_files INTEGER NOT NULL DEFAULT 0,
    js_lines INTEGER NOT NULL DEFAULT 0,
    css_files INTEGER NOT NULL DEFAULT 0,
    css_lines INTEGER NOT NULL DEFAULT 0,
    html_files INTEGER NOT NULL DEFAULT 0,
    html_lines INTEGER NOT NULL DEFAULT 0,
    sql_files INTEGER NOT NULL DEFAULT 0,
    sql_lines INTEGER NOT NULL DEFAULT 0,
    per_module JSONB DEFAULT '{}',
    scanned_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS code_audit_log (
    id SERIAL PRIMARY KEY,
    module_name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    files_reviewed INTEGER DEFAULT 0,
    lines_before INTEGER DEFAULT 0,
    lines_after INTEGER DEFAULT 0,
    issues_found INTEGER DEFAULT 0,
    issues_fixed INTEGER DEFAULT 0,
    notes TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    audited_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_code_metrics_scanned ON code_metrics_snapshots(scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_code_audit_module ON code_audit_log(module_name);
