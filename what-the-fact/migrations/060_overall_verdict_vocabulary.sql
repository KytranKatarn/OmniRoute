-- 060 — constrain wtf.fact_checks.overall_verdict to the documented rubric.
--
-- llm_analysis_backlog_worker.py carried this comment:
--     # fact_checks.overall_verdict CHECK: verified/mostly_true/mixed/disputed/unverifiable/NULL
-- There was NO such constraint. The column was free text, and ingest/run.py:253
-- wrote `verify_result.get("overall_verdict")` RAW from the model. An invariant
-- that only exists in a comment is not an invariant — that is exactly how the
-- drift below went unnoticed for the life of the column.
--
-- Measured 2026-08-31 across 427,757 rows:
--     unverifiable          218,668   ✓ canonical
--     (NULL)                130,363   ✓ allowed (analysis not run / no result)
--     unverified             32,919   ✗ PER-CLAIM vocabulary in the per-article column
--     verified               21,593   ✓
--     mixed                  15,825   ✓
--     mostly_true             6,437   ✓
--     descriptive_reporting     979   ✓
--     disputed                  691   ✓
--     true                      242   ✗ per-claim spelling of `verified`
--     verified_facts             21   ✗ model free text
--     factual_reporting           9   ✗ model free text
--     most_factual                3   ✗ model free text
--
-- ⚠️ `unverified` and `unverifiable` are NOT a typo pair — they are the correct
-- values of DIFFERENT columns (per-claim vs per-article). Migrating one to the
-- other is only right for `overall_verdict`; never do the reverse on `verdict`.
--
-- ⚠️ LOCK: this table takes continuous writes from the ingest pipeline. An
-- ALTER that has to WAIT puts itself at the head of a FIFO queue and stacks every
-- reader and writer behind it — that stalled ingest for over two minutes on
-- 2026-08-31. Hence: short lock_timeout, ADD ... NOT VALID (brief lock, NO table
-- scan), and VALIDATE as a SEPARATE statement (weaker SHARE UPDATE EXCLUSIVE).
-- Re-run the file until it succeeds; every statement is idempotent.

SET lock_timeout = '3s';

-- 1. canonicalize. Batched by value so each statement touches one small set;
--    the 32,919-row `unverified` update is the only large one.
UPDATE wtf.fact_checks SET overall_verdict = 'verified'
 WHERE overall_verdict IN ('true', 'verified_facts');

UPDATE wtf.fact_checks SET overall_verdict = 'mostly_true'
 WHERE overall_verdict = 'most_factual';

-- "factual reporting" describes the ARTICLE's character, not a verification
-- outcome — which is precisely what descriptive_reporting means.
UPDATE wtf.fact_checks SET overall_verdict = 'descriptive_reporting'
 WHERE overall_verdict = 'factual_reporting';

UPDATE wtf.fact_checks SET overall_verdict = 'unverifiable'
 WHERE overall_verdict = 'unverified';

-- Anything still outside the rubric becomes NULL rather than a guess: NULL means
-- "no adjudication recorded", which is honest. A wrong verdict renders on a
-- public accountability page.
UPDATE wtf.fact_checks SET overall_verdict = NULL
 WHERE overall_verdict IS NOT NULL
   AND overall_verdict NOT IN ('verified','mostly_true','mixed','disputed',
                               'unverifiable','descriptive_reporting');

-- 2. the constraint the code already believed existed. NOT VALID = no scan.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'wtf.fact_checks'::regclass
                      AND conname  = 'fact_overall_verdict_check') THEN
        ALTER TABLE wtf.fact_checks
            ADD CONSTRAINT fact_overall_verdict_check
            CHECK (overall_verdict IS NULL OR overall_verdict IN (
                'verified','mostly_true','mixed','disputed',
                'unverifiable','descriptive_reporting'
            )) NOT VALID;
    END IF;
END $$;

COMMENT ON COLUMN wtf.fact_checks.overall_verdict IS
  'PER-ARTICLE verdict: verified|mostly_true|mixed|disputed|unverifiable|descriptive_reporting, or NULL when no analysis was recorded. DISTINCT vocabulary from the per-claim `verdict` column — `unverified` belongs there, `unverifiable` belongs here. Canonicalize via ingest/verdicts.canonical_overall().';
