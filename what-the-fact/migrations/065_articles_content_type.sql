-- 065 — separate wire/press-release copy from journalism.
--
-- A press release has no political lean to measure. Scoring one does not give a
-- wrong answer, it gives a MEANINGLESS one — and that meaningless number was
-- then averaged into the outlet's public bias reading.
--
-- Measured on Financial Post, 30 days (2026-09-01):
--     wire copy      647 articles (43%)   avg bias -0.023
--     journalism     868 articles         avg bias -0.191
--     PUBLISHED      ----                 avg bias -0.107
-- The site reported -0.107 for an outlet whose journalism measures -0.191:
-- the published figure sat at the midpoint of two unrelated populations. That
-- is the difference between calling Financial Post "center" and "center-left".
--
-- Same defect class as migration 063 (no-signal heuristic rows). 063 handled
-- "the detector found nothing"; this handles "there was never anything
-- political to find". Both are absences being averaged as measurements.
--
-- ⚠️ DEFAULT 'journalism' IS THE FAIL-SAFE. A false positive here DELETES a
-- real signal from a public statistic, so an unrecognised article keeps
-- counting. Detection (ingest/content_kind.py) matches only distributor
-- boilerplate — never a topic, company name, or dateline guess.
--
-- ⚠️ New wtf columns must GRANT to wtfuser — apps do not connect as owner.

SET lock_timeout = '3s';

ALTER TABLE wtf.articles
    ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'journalism';

COMMENT ON COLUMN wtf.articles.content_type IS
  'journalism (default, fail-safe) | wire = press-release/newswire copy. Wire items are EXCLUDED from outlet bias averages and their political score is suppressed in the UI: there is no partisan lean in a corporate announcement, and averaging one in dilutes the outlet''s measured lean. Set by ingest/content_kind.classify() from distributor boilerplate only.';

-- Backfill. Mirrors _WIRE_MARKERS in ingest/content_kind.py — if you add a
-- marker there, the existing corpus is NOT reclassified until this runs again.
UPDATE wtf.articles SET content_type = 'wire'
 WHERE content_type = 'journalism'
   AND (
        body  ILIKE '%globe newswire%' OR body  ILIKE '%globenewswire%'
     OR body  ILIKE '%/CNW/%'          OR body  ILIKE '%cnw telbec%'
     OR body  ILIKE '%canada newswire%'
     OR body  ILIKE '%business wire%'  OR body  ILIKE '%businesswire%'
     OR body  ILIKE '%pr newswire%'    OR body  ILIKE '%prnewswire%'
     OR body  ILIKE '%accesswire%'     OR body  ILIKE '%newsfile corp%'
     OR body  ILIKE '%partnership content%'
     OR title ILIKE '%globe newswire%' OR title ILIKE '%globenewswire%'
   );

-- Partial index: the wire population is the minority (~2% overall, ~43% at
-- business outlets) and every consumer filters FOR or AGAINST it.
CREATE INDEX IF NOT EXISTS idx_articles_content_type_wire
    ON wtf.articles (source_id, published_at) WHERE content_type = 'wire';

GRANT SELECT ON wtf.articles TO wtfuser;
