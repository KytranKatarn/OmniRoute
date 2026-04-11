-- P.R.O.B.E. QA Testing Agent Tables
-- Date: 2026-04-09

CREATE TABLE IF NOT EXISTS qa_test_suites (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    target_url VARCHAR(500),
    spec JSONB NOT NULL,
    suite_type VARCHAR(50) DEFAULT 'internal'
        CHECK (suite_type IN ('internal', 'customer')),
    user_id INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qa_test_runs (
    id SERIAL PRIMARY KEY,
    suite_id INTEGER REFERENCES qa_test_suites(id),
    triggered_by VARCHAR(100),
    status VARCHAR(20) DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    duration_ms INTEGER,
    report_path VARCHAR(500),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qa_test_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES qa_test_runs(id),
    test_name VARCHAR(255) NOT NULL,
    test_type VARCHAR(50)
        CHECK (test_type IN ('api', 'page_load', 'e2e')),
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('pass', 'fail', 'error', 'skip')),
    url VARCHAR(500),
    method VARCHAR(10),
    expected_status INTEGER,
    actual_status INTEGER,
    response_time_ms INTEGER,
    error_message TEXT,
    screenshot_path VARCHAR(500),
    assertions JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_results_run_id ON qa_test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_qa_results_status ON qa_test_results(status);
CREATE INDEX IF NOT EXISTS idx_qa_runs_suite_id ON qa_test_runs(suite_id);
CREATE INDEX IF NOT EXISTS idx_qa_runs_status ON qa_test_runs(status);
CREATE INDEX IF NOT EXISTS idx_qa_suites_user_id ON qa_test_suites(user_id);
CREATE INDEX IF NOT EXISTS idx_qa_suites_active ON qa_test_suites(is_active);
