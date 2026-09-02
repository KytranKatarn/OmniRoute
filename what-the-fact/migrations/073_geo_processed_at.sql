-- 073_geo_processed_at.sql — make geo THROUGHPUT measurable (#6263)
--
-- WHY. `/activity` tried to show a geo burn-down:
--     geo_days_left = geo_pending / (geo_rate * 24)
-- and computed geo_rate from a column that DOES NOT EXIST (`geo_confidence`).
-- The whole "extra analytics" SELECT lived in one try/except, so the working
-- `llm_hr` metric in the same statement died with it — the LLM pipeline ran at
-- 103.5/hr while the public transparency page reported ZERO. Split in #6263.
--
-- ⚠️ THE OBVIOUS FIX WAS WRONG, and the numbers say so. Swapping the predicate to
-- `province_code IS NOT NULL AND published_at > NOW() - INTERVAL '6 hours'`
-- measures COVERAGE OF RECENT PUBLICATIONS, not throughput — a different
-- population from the backlog it would divide into. Measured 2026-09-02:
--
--     geo backlog (province_code IS NULL AND geo_scope <> 'unmappable') : 3,552
--       of which published MORE THAN 30 DAYS AGO                        : 1,905 (54%)
--     published in the last 6h                                          :   331
--       of those, geocoded                                              :   194
--
-- That yields geo_rate 32.3/hr and an ETA of **4.6 days** for a backlog whose
-- majority has already sat ungeocoded for over THIRTY days. Confidently wrong,
-- and wrong in the reassuring direction — the same shape as the phantom
-- `backups` table (#2366) and the declared-but-never-applied vps retention tier
-- (#5616): a number that renders plausibly and misleads.
--
-- The real problem was structural: NOTHING recorded WHEN geocoding happened.
-- articles carries published_at / ingested_at / ai_analyzed_at / tier1_at /
-- tier2_at / bias_v2_computed_at — and no geo timestamp. Throughput was
-- unmeasurable by construction, so the honest options were "delete the metric"
-- or "make it measurable". This is the second.
--
-- WHAT COUNTS AS PROCESSED. An article leaves the pending set TWO ways, and both
-- are L.O.C.A.L. finishing its work:
--   1. it gets a province_code            (successfully geocoded)
--   2. it is marked geo_scope='unmappable' (terminal — no Canadian match)
-- Both stamp geo_processed_at. Counting only (1) would understate the drain rate
-- and re-introduce a too-optimistic ETA, which is the bug this replaces.
--
-- NULL = "processed before this column existed, or not yet processed". The
-- column is deliberately NOT backfilled: inventing a timestamp from published_at
-- would fabricate a history that never happened, and the metric is a FORWARD
-- rate — it needs one interval of real data, not a synthetic past. Expect
-- geo_hr to read 0 until the first cycle after deploy. That is honest, and
-- distinguishable from the old failure because the query no longer throws.

ALTER TABLE wtf.articles
    ADD COLUMN IF NOT EXISTS geo_processed_at timestamptz;

COMMENT ON COLUMN wtf.articles.geo_processed_at IS
  'When L.O.C.A.L. finished geo for this article — set on BOTH a successful '
  'geocode and a terminal geo_scope=''unmappable''. NULL = pre-dates migration '
  '073 or not yet processed. Deliberately NOT backfilled: it measures a forward '
  'throughput rate, and a synthesised past would fabricate history (#6263).';

-- Partial index: every consumer of this column asks "how many in the last N
-- hours", so only non-NULL rows are ever scanned. Keeps the index small on a
-- table where the column will be NULL for every pre-existing row.
CREATE INDEX IF NOT EXISTS ix_articles_geo_processed_at
    ON wtf.articles (geo_processed_at)
    WHERE geo_processed_at IS NOT NULL;

-- wtfuser is the app role and does not own the table; new columns inherit table
-- grants, but the index/column combination is re-granted defensively — the
-- migration-047 lesson (apps do not connect as the owner, and a missing GRANT
-- surfaces as a runtime permission error, not a migration failure).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, UPDATE ON wtf.articles TO wtfuser;
    END IF;
END $$;
