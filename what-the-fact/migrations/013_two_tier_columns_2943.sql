-- 013_two_tier_columns_2943.sql
-- Phase A of #2943 two-tier LLM. Adds tier-tracking columns to wtf.articles
-- so Phase B (worker wiring) can record which tier produced each result and
-- which articles still need a Tier 2 upgrade.
--
-- See docs/two-tier-llm-design.md for the full design.
--
-- Idempotent — safe to re-run.

ALTER TABLE wtf.articles
  ADD COLUMN IF NOT EXISTS analysis_tier  VARCHAR(16) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS tier1_at       TIMESTAMP,
  ADD COLUMN IF NOT EXISTS tier2_at       TIMESTAMP,
  ADD COLUMN IF NOT EXISTS tier2_failures INTEGER     DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tier2_pending  BOOLEAN     DEFAULT FALSE;

COMMENT ON COLUMN wtf.articles.analysis_tier IS
  'Most recent tier that produced canonical results. Values: pending, quick_v1, quick_v1+full, quick_v1+failed.';

COMMENT ON COLUMN wtf.articles.tier1_at IS
  'Timestamp when Tier 1 (quick_v1) completed. NULL means never ran.';

COMMENT ON COLUMN wtf.articles.tier2_at IS
  'Timestamp when Tier 2 (full) completed. NULL means never ran (or skipped by gate).';

COMMENT ON COLUMN wtf.articles.tier2_failures IS
  'Consecutive Tier-2 failures for this article. Worker stops retrying after 3.';

COMMENT ON COLUMN wtf.articles.tier2_pending IS
  'TRUE when Tier 1 ran successfully but Tier 2 should still upgrade the result.';

-- Partial index — only stores rows actively awaiting a Tier 2 upgrade.
-- Worker queries: WHERE tier2_pending = TRUE ORDER BY tier1_at LIMIT N
CREATE INDEX IF NOT EXISTS idx_articles_tier2_pending
  ON wtf.articles(tier1_at) WHERE tier2_pending = TRUE;
