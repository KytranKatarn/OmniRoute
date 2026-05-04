-- Migration: P.R.O.B.E. perf baselines — add missing FKs + indexes
-- Spec: docs/superpowers/specs/2026-05-03-perf-baselines-design.md
-- Task: #1755 followup (code review)
-- Companion to: 369_qa_perf_baselines.sql

BEGIN;

-- FK: qa_perf_regressions.suite_id → qa_test_suites
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'qa_perf_regressions_suite_id_fkey'
    ) THEN
        ALTER TABLE qa_perf_regressions
            ADD CONSTRAINT qa_perf_regressions_suite_id_fkey
            FOREIGN KEY (suite_id) REFERENCES qa_test_suites(id) ON DELETE CASCADE;
    END IF;
END$$;

-- FK: qa_perf_acceptances.suite_id → qa_test_suites
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'qa_perf_acceptances_suite_id_fkey'
    ) THEN
        ALTER TABLE qa_perf_acceptances
            ADD CONSTRAINT qa_perf_acceptances_suite_id_fkey
            FOREIGN KEY (suite_id) REFERENCES qa_test_suites(id) ON DELETE CASCADE;
    END IF;
END$$;

-- Lookup indexes for hot paths
CREATE INDEX IF NOT EXISTS qa_perf_regressions_run_id
    ON qa_perf_regressions(run_id);

CREATE INDEX IF NOT EXISTS qa_perf_regressions_suite_test
    ON qa_perf_regressions(suite_id, test_name);

COMMIT;
