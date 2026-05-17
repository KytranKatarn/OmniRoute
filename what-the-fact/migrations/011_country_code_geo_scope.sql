-- 011_country_code_geo_scope.sql
-- L.O.C.A.L. Phase A — schema groundwork for global expansion (#2960) +
-- fix re-fetch loop where non-Canadian articles never leave 'national' (#2959).
--
-- Phase B (follow-up): expand the L.O.C.A.L. agent prompt to extract country
-- code for non-Canadian articles. This migration is prompt-agnostic — the
-- column accepts country codes but the LLM doesn't populate them yet.

-- ── #2960 country_code column ────────────────────────────────────────────
ALTER TABLE wtf.articles ADD COLUMN IF NOT EXISTS country_code VARCHAR(2);
COMMENT ON COLUMN wtf.articles.country_code IS 'ISO 3166-1 alpha-2 (CA, US, GB, ...). NULL = unknown.';

CREATE INDEX IF NOT EXISTS idx_articles_country ON wtf.articles(country_code) WHERE country_code IS NOT NULL;

-- Backfill: any article that already has a Canadian province or city is in Canada.
UPDATE wtf.articles
SET country_code = 'CA'
WHERE country_code IS NULL
  AND (province_code IS NOT NULL OR city IS NOT NULL);

-- ── #2959 terminal geo_scope ─────────────────────────────────────────────
-- CHECK constraint locks down the allowed states. 'unmappable' is the new
-- terminal state for articles where neither L.O.C.A.L. nor the heuristic
-- can determine a location — previously these reverted to 'national' and
-- got re-dispatched forever, burning agent cycles.
ALTER TABLE wtf.articles DROP CONSTRAINT IF EXISTS articles_geo_scope_check;
ALTER TABLE wtf.articles ADD CONSTRAINT articles_geo_scope_check
    CHECK (geo_scope IN ('national', 'provincial', 'municipal', 'international', 'unmappable'));
