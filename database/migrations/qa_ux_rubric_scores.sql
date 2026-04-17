-- P.R.O.B.E. UX Rubric Scores (Task #2029, 2026-04-16)
-- Stores vision-model UX scoring results per suite run + breakpoint.
-- Consumed by qa_ux_scorer.py; summary results also flow into
-- qa_test_results via the normal suite pipeline.

CREATE TABLE IF NOT EXISTS qa_ux_rubric_scores (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES qa_test_runs(id) ON DELETE CASCADE,
    suite_id INTEGER REFERENCES qa_test_suites(id),
    rubric_version TEXT NOT NULL DEFAULT 'probe-ux-rubric-v1',
    path TEXT NOT NULL,
    breakpoint INTEGER,
    scores JSONB NOT NULL,
    overall_score NUMERIC(4, 2) NOT NULL,
    passed BOOLEAN NOT NULL,
    model_used TEXT,
    rationale TEXT,
    screenshot_path TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_ux_rubric_scores_run ON qa_ux_rubric_scores(run_id);
CREATE INDEX IF NOT EXISTS idx_qa_ux_rubric_scores_suite ON qa_ux_rubric_scores(suite_id);
