-- Migration 401: ISED Voluntary Code self-assessment framework (T3258)
-- C.R.E.E.D. accountability pillar — periodic self-assessment against
-- Canada's Voluntary Code of Conduct on Responsible Generative AI (Sep 2023).
-- Stores structured questionnaire responses + computed scores per principle.

CREATE TABLE IF NOT EXISTS creed_ised_assessments (
    id              SERIAL PRIMARY KEY,
    code_version    VARCHAR(20) NOT NULL DEFAULT '1.0',
    conducted_by    VARCHAR(100) NOT NULL DEFAULT 'system',
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'in_progress', 'completed', 'published')),
    overall_score   DECIMAL(5, 2),          -- 0.00–100.00
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    published_at    TIMESTAMPTZ,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS creed_ised_responses (
    id              SERIAL PRIMARY KEY,
    assessment_id   INTEGER NOT NULL REFERENCES creed_ised_assessments(id) ON DELETE CASCADE,
    principle_id    VARCHAR(50) NOT NULL,   -- e.g. 'safety', 'privacy'
    question_id     VARCHAR(100) NOT NULL,  -- e.g. 'safety_q1'
    answer          VARCHAR(20)
        CHECK (answer IN ('yes', 'partial', 'no', 'na')),
    notes           TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(assessment_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_ised_assess_status   ON creed_ised_assessments(status);
CREATE INDEX IF NOT EXISTS idx_ised_assess_published ON creed_ised_assessments(published_at DESC)
    WHERE published_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ised_resp_assess      ON creed_ised_responses(assessment_id);
CREATE INDEX IF NOT EXISTS idx_ised_resp_principle   ON creed_ised_responses(principle_id);

COMMENT ON TABLE creed_ised_assessments IS
    'C.R.E.E.D. T3258 — periodic self-assessment against Canada ISED Voluntary Code (Sep 2023).';
COMMENT ON TABLE creed_ised_responses IS
    'Per-question answers for each ISED self-assessment run. '
    'answer: yes=full compliance, partial=in-progress, no=gap, na=not applicable.';
COMMENT ON COLUMN creed_ised_assessments.overall_score IS
    'Weighted average across all principles: yes=100, partial=50, no=0, na excluded.';
