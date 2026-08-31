-- 061 — retire the fabricated `unverifiable` on no-claims placeholder rows.
--
-- 133,991 rows (53.2% of ALL `unverifiable` verdicts) are placeholders written
-- when the model returned no claims. Four writers hardcoded 'unverifiable' into
-- the INSERT, discarding what the model actually said — and the prompt tells it
-- to say `descriptive_reporting` for exactly this case:
--
--     "If the article contains NO specific factual assertions (market summary,
--      breaking dispatch, sports score, weather report, wire copy):
--      Return {"claims": [], "overall_verdict": "descriptive_reporting"}"
--
--   unverifiable          = we tried to verify and could not.
--   descriptive_reporting = this article makes no checkable claim.
--
-- A sports score is not an unverified allegation. Those are different public
-- statements about a named publisher.
--
-- ⚠️ WHY NULL AND NOT `descriptive_reporting`.
-- Relabelling all 133,991 to descriptive_reporting would assert something the
-- data cannot support. A placeholder row has TWO indistinguishable causes:
--   (a) the model genuinely reported no claims  -> descriptive_reporting
--   (b) the response failed to parse, so `parsed = {}` and the old
--       `(parsed.get("overall_verdict") or "unverifiable")` FABRICATED a verdict
-- The model's original answer is not recoverable: wtf.llm_analyses holds the
-- deep_analysis task's output, not factcheck's, and carries `key_claims` for
-- only a minority of these articles (35,716 of 131,875 for dhq_v1).
--
-- Guessing (a) for all of them would repeat the exact absent-vs-measured error
-- this session already fixed twice — `float(x or 0.0)` in bias, and the `or
-- "unverifiable"` above. NULL is the honest statement: "no adjudication
-- recorded". Migration 060 set that precedent deliberately: a wrong verdict
-- renders on a public accountability page; an absent one does not.
--
-- These articles remain eligible for re-analysis by the FIXED pipeline, which
-- will now record descriptive_reporting where the model actually says it.
--
-- REVERSIBLE: wtf.fact_checks_placeholder_snapshot_20260831 holds every row.
-- ⚠️ New wtf tables must GRANT to wtfuser — the apps do not connect as owner.

SET lock_timeout = '3s';

-- 1. snapshot (idempotent: rebuilt each run, only ever holds placeholder rows)
DROP TABLE IF EXISTS wtf.fact_checks_placeholder_snapshot_20260831;
CREATE TABLE wtf.fact_checks_placeholder_snapshot_20260831 AS
SELECT id, article_id, claim, verdict, checker, analyzed_by, overall_verdict, checked_at
  FROM wtf.fact_checks
 WHERE overall_verdict = 'unverifiable'
   AND (claim = 'No verifiable claims detected.'
        OR claim LIKE '(no factual claims%');

GRANT SELECT ON wtf.fact_checks_placeholder_snapshot_20260831 TO wtfuser;

-- 2. batched by writer so each statement touches a smaller set — this table
--    takes continuous ingest writes and a long UPDATE puts itself at the head
--    of a FIFO lock queue, stalling every reader behind it (migration 060).
UPDATE wtf.fact_checks SET overall_verdict = NULL
 WHERE overall_verdict = 'unverifiable' AND analyzed_by = 'dhq_v1'
   AND claim = 'No verifiable claims detected.';

UPDATE wtf.fact_checks SET overall_verdict = NULL
 WHERE overall_verdict = 'unverifiable' AND analyzed_by = 'llm_v1'
   AND claim = 'No verifiable claims detected.';

UPDATE wtf.fact_checks SET overall_verdict = NULL
 WHERE overall_verdict = 'unverifiable' AND analyzed_by = 'dhq_backlog_v1'
   AND claim = 'No verifiable claims detected.';

UPDATE wtf.fact_checks SET overall_verdict = NULL
 WHERE overall_verdict = 'unverifiable'
   AND claim = 'No verifiable claims detected.';   -- any remaining writer

UPDATE wtf.fact_checks SET overall_verdict = NULL
 WHERE overall_verdict = 'unverifiable'
   AND claim LIKE '(no factual claims%';           -- backlog-worker placeholder

-- 3. rollback, if ever needed:
--    UPDATE wtf.fact_checks f SET overall_verdict = s.overall_verdict
--      FROM wtf.fact_checks_placeholder_snapshot_20260831 s WHERE s.id = f.id;
