-- 070: give every suppressed duplicate a POINTER to its survivor, then use it to
--      repair the shared entity graph.
--
-- WHY THIS COLUMN HAS TO EXIST
-- ----------------------------
-- 068 suppressed 8,288 re-fetched duplicates but recorded only THAT they were
-- duplicates (`suppressed_reason`), never OF WHAT. `suppressed_reason` was the
-- only suppression column on the table. That single omission blocks two separate
-- fixes:
--
--   * ~8,300 live URLs currently return 200 with a hidden article. The correct
--     answer for a duplicate is a 301 to the canonical copy — which is
--     unimplementable without knowing the target.
--   * 297 shared.entity_mentions point at suppressed articles. They cannot be
--     re-pointed to the survivor for the same reason, and deleting them outright
--     would drop ONE entity out of the WTF graph entirely (measured: exactly one
--     entity has no mention on any visible article).
--
-- The relationship was always derivable but was never DATA, so nothing could act
-- on it. This makes it data.
--
-- RECONSTRUCTING THE SURVIVOR
-- ---------------------------
-- 068's rule was "suppress `a` if a better row exists in the same (source_id,
-- title, ±6h) group", better = longer body, tie-break lower id. Inverting it
-- gives the survivor.
--
-- ⚠️ THE ±6h WINDOW IS NOT TRANSITIVE, and that matters here. A–B within 6h and
-- B–C within 6h does NOT put A and C within 6h, and 068 suppressed transitively
-- through EXISTS chains — so a row can be suppressed by a sibling that is itself
-- suppressed. Applying the windowed lookup to find the survivor left **502 of
-- 8,288 unresolvable**, which reads like data corruption and is not.
--
-- Measured: **0** groups exist where every member is suppressed — i.e. every one
-- of those 502 DOES have a visible same-title sibling, just outside its own
-- window. So the pointer lookup drops the time window (same source + byte-identical
-- title is already the duplicate criterion; the window was there to bound
-- SUPPRESSION, and that decision is made and not being revisited). Window-free:
-- **8,288 resolvable, 0 unresolvable, 0 self-references.**
--
-- Deliberately scoped to `duplicate_refetch`. `publisher_suffix_title` articles
-- are junk, not duplicates — they have no survivor to point at and stay NULL.
--
-- IDEMPOTENT. Re-running recomputes the same pointers and inserts no new mentions.

BEGIN;

-- ── 1. the pointer ───────────────────────────────────────────────────────────
ALTER TABLE wtf.articles
  ADD COLUMN IF NOT EXISTS canonical_article_id INTEGER REFERENCES wtf.articles(id);

COMMENT ON COLUMN wtf.articles.canonical_article_id IS
  'For a suppressed duplicate: the surviving article it duplicates. NULL for '
  'visible articles and for suppression reasons that are not duplication '
  '(e.g. publisher_suffix_title, which has no survivor). Drives the 301 on '
  '/article/<id> and the entity-graph re-point. See migration 070.';

-- ── 2. backfill ──────────────────────────────────────────────────────────────
UPDATE wtf.articles d
   SET canonical_article_id = (
        SELECT k.id FROM wtf.articles k
         WHERE k.source_id = d.source_id
           AND k.title     = d.title
           AND k.suppressed_reason IS NULL
         ORDER BY COALESCE(length(k.body), 0) DESC, k.id ASC
         LIMIT 1)
 WHERE d.suppressed_reason = 'duplicate_refetch'
   AND d.canonical_article_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_articles_canonical
    ON wtf.articles (canonical_article_id) WHERE canonical_article_id IS NOT NULL;

-- ── 3. repair the shared entity graph ────────────────────────────────────────
-- RE-POINT, don't delete. A mention on a duplicate is evidence the entity was in
-- that story; the survivor tells the same story. Deleting outright would silently
-- shrink the cross-product graph that Gov/Legal/Market/Civic all read.
--
-- Insert-then-delete rather than UPDATE, because (entity_id, product,
-- content_type, content_id) is UNIQUE and the survivor usually ALREADY carries
-- the same entity — a bare UPDATE would raise on the common case.
INSERT INTO shared.entity_mentions
       (entity_id, product, content_type, content_id, mention_context, confidence)
SELECT m.entity_id, m.product, m.content_type, a.canonical_article_id::text,
       m.mention_context, m.confidence
  FROM shared.entity_mentions m
  JOIN wtf.articles a ON a.id::text = m.content_id
 WHERE m.product = 'wtf' AND m.content_type = 'article'
   AND a.canonical_article_id IS NOT NULL
ON CONFLICT (entity_id, product, content_type, content_id) DO NOTHING;

-- Now the carried-across pointers can go.
--
-- ⚠️ `canonical_article_id IS NOT NULL` is LOAD-BEARING, not redundant with the
-- suppression check. Deleting on `suppressed_reason IS NOT NULL` would also take
-- the 1 mention sitting on a `publisher_suffix_title` article — which has NO
-- canonical and was therefore NEVER carried across by the INSERT above. That row
-- would be destroyed with no replacement, which is precisely what the re-point
-- exists to avoid. Delete only what was actually copied.
DELETE FROM shared.entity_mentions m
 USING wtf.articles a
 WHERE a.id::text = m.content_id
   AND m.product = 'wtf' AND m.content_type = 'article'
   AND a.canonical_article_id IS NOT NULL;

COMMIT;
