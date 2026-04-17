-- P.R.O.B.E. Tab Interaction Test Type (Task #2013, 2026-04-17)
-- Extends qa_test_results.test_type CHECK to accept 'tab_interaction'.
-- Part of encoding the manual Account Center UX tour as automated coverage.

ALTER TABLE qa_test_results DROP CONSTRAINT IF EXISTS qa_test_results_test_type_check;
ALTER TABLE qa_test_results ADD CONSTRAINT qa_test_results_test_type_check
    CHECK (test_type IN (
        'api',
        'page_load',
        'e2e',
        'visual_snapshot',
        'template_analysis',
        'ux_score',
        'tab_interaction'
    ));
