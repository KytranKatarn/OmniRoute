-- 368_qa_faith_devotional_timeout.sql
-- F.A.I.T.H. devotional QA test needs >30s for cold-load + generation.
--
-- The agent is barracked when not actively used; the dispatch path wakes
-- it on demand, then loads the model (~10-60s for a 7B model under
-- KEEP_ALIVE=5m), then generates a multi-paragraph devotional. Total
-- runtime can hit 60-120s on a cold path. The QA spec runner now honours
-- per-test ``timeout_ms``; this migration sets 120000ms on the
-- /api/faith/devotional test only, leaving the other 4 faith.yaml tests
-- on the 30s default.
--
-- Idempotent: only updates rows where the timeout_ms key is missing.

UPDATE qa_test_suites
SET spec = jsonb_set(
    spec,
    '{tests}',
    (
        SELECT jsonb_agg(
            CASE
                WHEN t->>'name' = 'faith-tools-faith-api-faith-devotional'
                  AND NOT (t ? 'timeout_ms')
                  THEN t || '{"timeout_ms": 120000}'::jsonb
                ELSE t
            END
        )
        FROM jsonb_array_elements(spec->'tests') t
    )
)
WHERE name = 'faith.yaml'
  AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(spec->'tests') t
      WHERE t->>'name' = 'faith-tools-faith-api-faith-devotional'
        AND NOT (t ? 'timeout_ms')
  );
