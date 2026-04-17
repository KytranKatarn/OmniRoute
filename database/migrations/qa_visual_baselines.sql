-- P.R.O.B.E. Visual Snapshot Baselines (Task #2027, 2026-04-16)
-- Additive to qa_tables.sql — stores computed-style + selector snapshots per breakpoint.
-- Relaxes qa_test_results.test_type CHECK to allow visual_snapshot, template_analysis, ux_score.

CREATE TABLE IF NOT EXISTS qa_visual_baselines (
    id SERIAL PRIMARY KEY,
    suite_id INTEGER NOT NULL REFERENCES qa_test_suites(id) ON DELETE CASCADE,
    snapshot_name VARCHAR(255) NOT NULL,
    breakpoint INTEGER NOT NULL,
    baseline JSONB NOT NULL,
    captured_from_run_id INTEGER REFERENCES qa_test_runs(id) ON DELETE SET NULL,
    captured_at TIMESTAMP DEFAULT NOW(),
    captured_by INTEGER,
    UNIQUE (suite_id, snapshot_name, breakpoint)
);

CREATE INDEX IF NOT EXISTS idx_qa_visual_baselines_suite ON qa_visual_baselines(suite_id);

-- Extend test_type CHECK so new runners can write results without violating the constraint.
ALTER TABLE qa_test_results DROP CONSTRAINT IF EXISTS qa_test_results_test_type_check;
ALTER TABLE qa_test_results ADD CONSTRAINT qa_test_results_test_type_check
    CHECK (test_type IN ('api', 'page_load', 'e2e', 'visual_snapshot', 'template_analysis', 'ux_score'));
