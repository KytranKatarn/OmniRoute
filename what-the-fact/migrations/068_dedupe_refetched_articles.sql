-- 068: suppress re-fetched duplicate articles, and index the guard that stops new ones.
--
-- WHY
-- ---
-- `wtf.articles` has ONE dedupe key: UNIQUE (source_id, external_id), enforced by
-- `ON CONFLICT (source_id, external_id) DO NOTHING` in ingest/persist.py. There
-- is no constraint on url.
--
-- 10 of 46 sources are ingested through a GOOGLE NEWS PROXY, which re-encodes the
-- same story under a NEW opaque token on a later poll:
--
--   .../rss/articles/CBMigwFBVV95cUxNMTVaVWFxRmVvbk1JWmZCRHdt…?oc=5
--   .../rss/articles/CBMikwFBVV95cUxPNUVzb081M2p6YTB0QWQwSC11…?oc=5
--
-- Same headline, same published_at, two tokens. external_id AND url both change,
-- so the unique key cannot see it and a url constraint would not have either.
--
-- MEASURED, 14 days:
--     same-source same-title groups            796
--     redundant rows                           953   (6.3% of 15,021 articles)
--     ...of which had DIFFERENT urls           792   (only 4 were url-dedupable)
--     CTV News alone                           571 groups
--
-- ⚠️ I FIRST DIAGNOSED THIS WRONG. Three hand-picked examples happened to share a
-- byte-identical CBC url, so the obvious conclusion was "GUID churn, add a url
-- key". Measuring the whole population instead of the examples showed 792 of 796
-- have DIFFERENT urls — a url constraint would have fixed 4 of 796 while looking
-- like a fix.
--
-- THE 6-HOUR WINDOW IS LOAD-BEARING
-- ---------------------------------
-- Spread within duplicate groups, 14d:
--
--     < 1h    623 groups   ← the re-fetch signature
--     1-6h     79
--     6-24h    28
--     24-72h    8
--     > 72h    58          ← NOT duplicates
--
-- The >72h bucket is RECURRING CONTENT that legitimately reuses a headline:
-- "Today's horoscope" x8, "Before the Bell: What every Canadian investor needs to
-- know" x10 (a daily column), "Transaction in Own Shares" x8 (a recurring filing).
-- Deduping on title alone — or with a window of a day or more — would silently
-- delete a publisher's daily column down to one copy. 6h sits above the entire
-- re-fetch population and far below any daily recurrence.
--
-- WHICH ROW SURVIVES
-- ------------------
-- The one with the LONGEST BODY (so a captured body is never traded for a stub),
-- tie-broken by the LOWEST id (earliest, deterministic). Comparisons run against
-- the pre-UPDATE snapshot, so in a group of N every row except the single best
-- one is suppressed — the best row has nobody better and survives.
--
-- ⚠️ SUPPRESSED, NOT DELETED. `suppressed_reason` already hides a row from every
-- reader path (idx_articles_visible, the front page, clusters, digests) and is
-- reversible with one UPDATE. These are real fetches with real audit trails and
-- fact-check rows hanging off them; deleting would cascade.
--
-- PREDICTED BEFORE RUNNING: 8,288 of 123,617 rows suppressed (6.7%), and 0 groups
-- losing every member.
--
-- IDEMPOTENT: re-running suppresses nothing further (survivors have no better
-- unsuppressed peer, and already-suppressed rows are excluded).

BEGIN;

-- Supports the WHERE NOT EXISTS guard now inside the ingest INSERT, which probes
-- (source_id, title, published_at) on every single article ingested.
CREATE INDEX IF NOT EXISTS idx_articles_source_title_published
    ON wtf.articles (source_id, title, published_at);

UPDATE wtf.articles a
   SET suppressed_reason = 'duplicate_refetch'
 WHERE a.suppressed_reason IS NULL
   AND EXISTS (
        SELECT 1
          FROM wtf.articles k
         WHERE k.source_id = a.source_id
           AND k.title     = a.title
           AND k.id       <> a.id
           AND k.suppressed_reason IS NULL
           AND k.published_at BETWEEN a.published_at - INTERVAL '6 hours'
                                  AND a.published_at + INTERVAL '6 hours'
           -- "k is a better copy than a": richer body wins, else lower id wins.
           AND (   COALESCE(length(k.body), 0) >  COALESCE(length(a.body), 0)
                OR (COALESCE(length(k.body), 0) = COALESCE(length(a.body), 0)
                    AND k.id < a.id))
   );

COMMIT;
