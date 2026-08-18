-- 056: keep La Presse in the corpus, but stop it arriving through a Google News
-- proxy — and give the corpus a reversible way to hide unusable rows (#5775).
--
-- OWNER DECISION 2026-08-18: "la press is still part of chorus" — La Presse
-- STAYS. So this repairs the sourcing rather than dropping the publisher.
--
-- WHAT WAS WRONG. wtf.sources id=491 pointed at
--     https://news.google.com/rss/search?q=site:lapresse.ca&hl=en-CA&gl=CA&ceid=CA:en
-- i.e. La Presse was NOT ingested from La Presse. Consequences, all measured:
--   · 74 of 180 titles were the literal publisher suffix "- La Presse+" — Google's
--     leftover when it has no headline. Not a headline; a scraping artifact.
--   · ALL 180 rows carry a news.google.com redirect URL. ZERO point at
--     lapresse.ca, so the "source" link never reached the source.
--   · published_at scatters to 2006/2013/2015/2017 — the proxy's date, not the
--     publication date.
--   · La Presse was the ONLY source site-wide under 50% title uniqueness.
--   · note the locale: hl=en-CA / ceid=CA:en — an ENGLISH query for a French
--     publisher, which is the likely reason headlines came back empty.
--
-- ⚠️ 10 of 46 sources use a Google News feed. This migration fixes the one that
-- is demonstrably broken; the other 9 are NOT touched here and are NOT assumed
-- broken (they pass the title-uniqueness check). Task #5775 carries the audit.

-- ── 1. reversible suppression, because DELETE would destroy real analysis ────
-- The 74 junk rows are referenced by 74 bias_scores, 242 fact_checks, 73
-- summaries and 74 cluster memberships. Deleting them would cascade into
-- published analysis to remove a bad headline. Suppression hides them from
-- readers while leaving the analytical record intact and the action reversible
-- (set the column back to NULL).
--
-- Mirrors the shared.entities precedent: that graph is IMMUTABLE and rows are
-- retired via status='suppressed' rather than deleted.
ALTER TABLE wtf.articles ADD COLUMN IF NOT EXISTS suppressed_reason text;
COMMENT ON COLUMN wtf.articles.suppressed_reason IS
  'NULL = visible. Non-NULL hides the row from reader-facing surfaces without '
  'deleting it or its downstream analysis. Set by data-quality fixes; reversible.';
CREATE INDEX IF NOT EXISTS idx_articles_visible
    ON wtf.articles (source_id, published_at DESC) WHERE suppressed_reason IS NULL;

UPDATE wtf.articles
   SET suppressed_reason = 'publisher_suffix_title'
 WHERE source_id = 491
   AND title ~ '^\s*-\s*La Presse'
   AND suppressed_reason IS NULL;

-- ── 2. point La Presse at its OWN feed ──────────────────────────────────────
-- Verified live 2026-08-18: https://www.lapresse.ca/actualites/rss -> HTTP 200,
-- channel title "LaPresse.ca - Actualités", 10 items, real French headlines
-- ("Le NPD appelle à enquêter sur le gouvernement pour écoblanchiment") and real
-- lapresse.ca article URLs. /manchettes/rss also works (8 items) if a second
-- section is ever wanted.
UPDATE wtf.sources
   SET rss_feed = 'https://www.lapresse.ca/actualites/rss'
 WHERE id = 491
   AND rss_feed ILIKE '%news.google%';

-- ── 3. report what is still proxied, so this cannot be forgotten ────────────
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT s.id, s.name,
               count(a.id) AS arts,
               round(100.0 * count(DISTINCT a.title) / NULLIF(count(a.id), 0), 1) AS pct_unique
        FROM wtf.sources s
        LEFT JOIN wtf.articles a ON a.source_id = s.id
        WHERE s.rss_feed ILIKE '%news.google%'
        GROUP BY s.id, s.name
        ORDER BY 4 NULLS FIRST
    LOOP
        RAISE NOTICE 'still google-proxied: % (%) — % articles, %%% unique titles',
            r.id, r.name, r.arts, r.pct_unique;
    END LOOP;
END $$;
