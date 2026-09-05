-- Migration 078: articles.latest_verdict (task #16, /news verdict filter)
--
-- Enables a real verdict filter on /news without the correlated-subquery cost
-- that made it unsafe to bolt onto the existing top_recent CTE (measured:
-- filtering rare verdicts like 'disputed' (531 of 119,574 articles) or
-- 'mostly_true' (28 total) via a per-row LATERAL scan needs to walk deep into
-- the table on every cache-miss filter combination — exactly the shape of
-- abuse this route already survived twice, #5719 and the 2026-08-30 bot
-- flood). This denormalizes the "latest non-GoogleFCT overall_verdict" for
-- an article onto articles itself, indexed, so it filters exactly like
-- province_code/beat/geo_scope already do.
--
-- Kept current by a trigger, NOT by touching the 6 separate ingest call
-- sites that write fact_checks (ingest/factcheck.py, tier2_upgrade.py,
-- factcheck_partner_worker.py, factcheck_backlog_worker.py,
-- llm_analysis_backlog_worker.py, tech/routes.py) — a write-through column
-- update at each site is a correctness footgun (miss one, or a 7th site
-- added later, and that pipeline's articles silently stop filtering
-- correctly). A single AFTER trigger on fact_checks can't be missed
-- regardless of how many write paths exist.

ALTER TABLE wtf.articles ADD COLUMN IF NOT EXISTS latest_verdict character varying(50);

ALTER TABLE wtf.articles DROP CONSTRAINT IF EXISTS article_latest_verdict_check;
ALTER TABLE wtf.articles ADD CONSTRAINT article_latest_verdict_check
    CHECK (latest_verdict IS NULL OR latest_verdict::text = ANY (ARRAY[
        'verified', 'mostly_true', 'mixed', 'disputed', 'unverifiable', 'descriptive_reporting'
    ]::text[]));
-- Mirrors wtf.fact_checks' own fact_overall_verdict_check verbatim — if that
-- enum ever changes, this one must change with it or the trigger's own
-- recomputed value could violate this constraint on the very next write.

-- Composite + partial to match the query shape this exists for: "articles
-- with suppressed_reason IS NULL AND latest_verdict = X, newest first" —
-- the same shape as the existing ix_articles_published_at walk, just scoped
-- to one verdict.
CREATE INDEX IF NOT EXISTS idx_articles_latest_verdict
    ON wtf.articles (latest_verdict, published_at DESC)
    WHERE suppressed_reason IS NULL;

CREATE OR REPLACE FUNCTION wtf.sync_article_latest_verdict() RETURNS trigger AS $$
DECLARE
    aid integer := COALESCE(NEW.article_id, OLD.article_id);
BEGIN
    UPDATE wtf.articles
    SET latest_verdict = (
        SELECT fc2.overall_verdict
        FROM wtf.fact_checks fc2
        WHERE fc2.article_id = aid AND fc2.checker NOT LIKE 'GoogleFCT%'
        ORDER BY fc2.id DESC
        LIMIT 1
    )
    WHERE id = aid;
    RETURN NULL;  -- AFTER trigger, return value is ignored
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_article_latest_verdict ON wtf.fact_checks;
CREATE TRIGGER trg_sync_article_latest_verdict
    AFTER INSERT OR UPDATE OF overall_verdict, checker OR DELETE ON wtf.fact_checks
    FOR EACH ROW EXECUTE FUNCTION wtf.sync_article_latest_verdict();

-- One-time backfill for the 119,574 pre-existing articles. Idempotent —
-- re-running this after the trigger is live is a harmless no-op recompute,
-- not a duplicate-write risk (plain UPDATE, no INSERT).
--
-- NOTE: a `FROM LATERAL (...)` correlated to the UPDATE target itself is NOT
-- valid Postgres (the target relation isn't exposed as a FROM-list item for
-- LATERAL correlation) — confirmed live: "invalid reference to FROM-clause
-- entry for table a". A scalar subquery in SET, same shape the trigger
-- function above already uses, is the correct form.
UPDATE wtf.articles a
SET latest_verdict = (
    SELECT fc2.overall_verdict
    FROM wtf.fact_checks fc2
    WHERE fc2.article_id = a.id AND fc2.checker NOT LIKE 'GoogleFCT%'
    ORDER BY fc2.id DESC
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1 FROM wtf.fact_checks fc2
    WHERE fc2.article_id = a.id AND fc2.checker NOT LIKE 'GoogleFCT%'
      AND fc2.overall_verdict IS NOT NULL
);
