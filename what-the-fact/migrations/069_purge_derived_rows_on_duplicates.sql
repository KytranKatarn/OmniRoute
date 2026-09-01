-- 069: remove derived analysis for suppressed DUPLICATES, and leave those rows in a
--      consistent state.
--
-- WHY
-- ---
-- #3036 suppressed 8,288 re-fetched duplicates. Each had already been independently
-- bias-scored, fact-checked and LLM-analysed before we knew it was a duplicate, so
-- the derived rows stayed behind:
--
--     fact_checks    27,317
--     llm_analyses    9,216
--     bias_scores     8,288
--                    -------
--                    44,821
--
-- They are invisible to every reader path, but they are COUNTED — the transparency
-- page reports `COUNT(*) FROM fact_checks` unfiltered, so the published
-- "fact-checked" figure includes 27,317 checks on articles nobody can read. That is
-- the same defect this whole line of work has been about: a published number that
-- counts something the site does not serve.
--
-- ⚠️ DELETION IS NOT THE WHOLE FIX. It corrects today's number; the missing filter
-- is the actual defect and would recur for the `publisher_suffix_title` population
-- (74 articles) and any future suppression reason. The count filters are fixed
-- separately — this migration is the data half only.
--
-- SCOPE — DELIBERATELY NARROW
-- ---------------------------
-- ONLY `suppressed_reason = 'duplicate_refetch'`. There are three reasons live:
--     (visible)                115,279
--     duplicate_refetch          8,288   <- this migration
--     publisher_suffix_title        74   <- untouched
-- A duplicate's analysis is redundant BY DEFINITION: the surviving copy carries its
-- own. That is not true of the other populations, so they are left alone.
--
-- ⚠️ audit_trail is KEPT (16,530 rows). It records that an ingest HAPPENED — that is
-- provenance, not derived analysis. On a product whose pitch is transparency,
-- deleting the record that something occurred is a different act from deleting a
-- recomputable score.
--
-- ⚠️ wtf.summaries is NOT TOUCHED. Its key is `article_ids` (PLURAL, an array) —
-- summaries are CLUSTER-level and one can span both suppressed and visible
-- articles. Deleting "the summaries for this article" would silently destroy a
-- summary that still serves visible ones. Caught only by the column name.
--
-- CONSISTENCY AFTER DELETION
-- --------------------------
-- Deleting the scores while leaving `ai_analyzed = true` would create a NEW
-- inconsistency: a row claiming it was analysed with no analysis behind it. If such
-- a row were ever un-suppressed (the reversal path for a wrong dedupe) it would
-- render an empty bias panel and never be re-analysed, because every producer gates
-- on ai_analyzed.
--
-- So the flags are reset too. The row then honestly says "not analysed", and if it
-- is ever un-suppressed the normal backlog re-analyses it. This is only safe
-- BECAUSE #3037 made the producers skip suppressed rows — without that, resetting
-- the flags would march all 8,288 straight back into the work queue.
--
-- RECOVERY
-- --------
-- Deleted rows are copied to wtf.purged_dupe_analysis_069 first. Restore is a plain
-- INSERT ... SELECT from those tables. Drop them once you are satisfied.
--
-- IDEMPOTENT: re-running deletes nothing further and resets nothing further.

BEGIN;

-- ── keep a copy before deleting anything ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS wtf.purged_069_fact_checks AS
  SELECT f.* FROM wtf.fact_checks f JOIN wtf.articles a ON a.id = f.article_id
   WHERE a.suppressed_reason = 'duplicate_refetch';

CREATE TABLE IF NOT EXISTS wtf.purged_069_bias_scores AS
  SELECT b.* FROM wtf.bias_scores b JOIN wtf.articles a ON a.id = b.article_id
   WHERE a.suppressed_reason = 'duplicate_refetch';

CREATE TABLE IF NOT EXISTS wtf.purged_069_llm_analyses AS
  SELECT l.* FROM wtf.llm_analyses l JOIN wtf.articles a ON a.id = l.article_id
   WHERE a.suppressed_reason = 'duplicate_refetch';

-- ── delete the derived analysis ──────────────────────────────────────────────
DELETE FROM wtf.fact_checks f
 USING wtf.articles a
 WHERE a.id = f.article_id AND a.suppressed_reason = 'duplicate_refetch';

DELETE FROM wtf.llm_analyses l
 USING wtf.articles a
 WHERE a.id = l.article_id AND a.suppressed_reason = 'duplicate_refetch';

DELETE FROM wtf.bias_scores b
 USING wtf.articles a
 WHERE a.id = b.article_id AND a.suppressed_reason = 'duplicate_refetch';

-- ── leave the articles honestly marked "not analysed" ────────────────────────
UPDATE wtf.articles
   SET ai_analyzed        = false,
       ai_analyzed_at     = NULL,
       analysis_tier      = 'pending',
       tier2_pending      = false,
       bias_v2_score      = NULL,
       bias_v2_label      = NULL,
       bias_v2_confidence = NULL,
       bias_v2_model      = NULL,
       bias_ensemble_score = NULL,
       bias_ensemble_band  = NULL
 WHERE suppressed_reason = 'duplicate_refetch'
   AND (ai_analyzed OR bias_v2_score IS NOT NULL OR analysis_tier <> 'pending');

COMMIT;
