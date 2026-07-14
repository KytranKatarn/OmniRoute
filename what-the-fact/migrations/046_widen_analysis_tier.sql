-- 046_widen_analysis_tier.sql
-- Fix: wtf.articles.analysis_tier was VARCHAR(16) (migration 013), too small for the
-- legit value 'quick_v1_failed+full' (20 chars) that ingest/tier_router.py emits when
-- Tier-1 fails but Tier-2 runs. The oversized value threw
-- psycopg2.errors.StringDataRightTruncation, which killed the ingest/analysis loop →
-- the what-the-fact.com front page froze (no new articles). 2026-07-14.
--
-- Widen to VARCHAR(32) (longest current label = 20, comfortable headroom).
-- Idempotent: only alters when the column is currently narrower than 32 (skips if the
-- live hot-fix already applied it, or if a future migration widens it further / to TEXT).

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'wtf' AND table_name = 'articles'
      AND column_name = 'analysis_tier'
      AND character_maximum_length IS NOT NULL
      AND character_maximum_length < 32
  ) THEN
    ALTER TABLE wtf.articles ALTER COLUMN analysis_tier TYPE varchar(32);
  END IF;
END $$;
