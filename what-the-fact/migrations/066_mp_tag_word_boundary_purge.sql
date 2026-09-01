-- 066: purge substring-accident MP tags, and record how each survivor matched.
--
-- WHY
-- ---
-- `ingest/parliament/openparl.tag_articles` matched MP names with a bare Python
-- substring test:
--
--     if any(p.lower() in text_blob.lower() for p in patterns)
--
-- with `patterns = [full_name] + [family_name if len >= 5]`. There is no word
-- boundary, so a surname matched inside ordinary words:
--
--     "chang"  -> "exchange", "changing", "changed"      (Wade Chang)
--     "grant"  -> "granted", "immigrant", "grants"       (Wade Grant)
--     "block"  -> "blocked", "roadblock"                 (Kelly Block)
--     "small"  -> "smaller"                              (Clifford Small)
--     "fisher" -> "fisheries"
--     "church" -> "church"
--
-- Measured over 7 days of live tags: 961 of 2,353 (40.8%) matched NOTHING at a
-- word boundary. Wade Chang alone was attached to 521 articles because they
-- contained the word "change". Across the whole table: 14,158 of 26,844 (52.7%).
--
-- WHY THIS MATTERS MORE THAN A COUNT
-- ----------------------------------
-- These tags name a REAL SITTING MP on a public article page. An article titled
-- "For Hamiltonians battling addiction, peer support is a dose of empathy" was
-- publicly tagged with MP Wade Grant, and the row was copied into
-- shared.entity_mentions at confidence 0.950. On a site whose product is
-- fact-checking, asserting that a named politician is connected to a story they
-- have nothing to do with is the worst class of error available.
--
-- WHAT IS KEPT, AND WHY match_type NOW MEANS SOMETHING
-- ---------------------------------------------------
-- Every row previously carried the literal string 'name_match', which said
-- nothing about the strength of the evidence. Survivors are now labelled:
--
--   'full_name'    the MP's full name appears at a word boundary (case-insensitive)
--   'family_name'  only the surname appears, at a word boundary, CAPITALISED
--
-- The family-name tier is deliberately case-SENSITIVE: many MP surnames are
-- common English nouns, and "the grant was awarded" is not a reference to Wade
-- Grant while "Grant said" probably is. That rule alone dropped a further 326
-- of the 1,064 family-only matches in the 7-day sample.
--
-- A bare surname stays WEAK EVIDENCE even after both rules. It is kept in the
-- table for the entity graph, but read paths that assert something in public
-- filter on match_type = 'full_name' (see STRONG_MATCH_TYPES in openparl.py).
--
-- ⚠️ The bodies are matched as they exist NOW. A tag whose name is absent from
-- the current title+body is not defensible against what the page renders today,
-- which is the only thing a reader can check. Bodies are only ever filled in by
-- capture, never emptied, so this cannot delete a tag that was fair when made.
--
-- IDEMPOTENT: re-running deletes nothing further and re-labels identically.

BEGIN;

-- 0. Classify EVERY tag exactly once, into a temp table.
--
-- ⚠️ DO NOT inline these predicates into the DELETEs. The first draft used a
--    correlated `EXISTS (... regex ...)` inside the entity_mentions DELETE; the
--    planner re-evaluated two regexes per (mention x tag) pair and the statement
--    was still running after 7 minutes, holding locks on shared.entity_mentions
--    — a table three other products write to. Materialising the verdict first
--    makes every later step an indexed join.
CREATE TEMP TABLE _mp_tag_verdict ON COMMIT DROP AS
SELECT t.article_id,
       t.mp_id,
       m.entity_id,
       CASE
         WHEN LEFT(COALESCE(a.title,'') || ' ' || COALESCE(a.body,''), 2000)
              ~* ('\y' || m.name || '\y')                       THEN 'full_name'
         WHEN m.family_name IS NOT NULL
              AND LENGTH(m.family_name) >= 5
              AND LEFT(COALESCE(a.title,'') || ' ' || COALESCE(a.body,''), 2000)
                  ~ ('\y' || m.family_name || '\y')             THEN 'family_name'
         ELSE NULL                                    -- substring accident
       END AS verdict
  FROM wtf.article_mp_tags t
  JOIN parliament.mps m ON m.id = t.mp_id
  JOIN wtf.articles   a ON a.id = t.article_id;

CREATE INDEX ON _mp_tag_verdict (article_id, mp_id);
CREATE INDEX ON _mp_tag_verdict (entity_id, article_id);
ANALYZE _mp_tag_verdict;

-- 1. Label the survivors, from the same verdict the delete uses.
UPDATE wtf.article_mp_tags t
   SET match_type = v.verdict
  FROM _mp_tag_verdict v
 WHERE v.article_id = t.article_id
   AND v.mp_id      = t.mp_id
   AND v.verdict IS NOT NULL
   AND t.match_type IS DISTINCT FROM v.verdict;

-- 2. Drop the MP-derived entity_mentions for the tags about to be purged.
--    Joined on entity_id, so only mentions that came from an MP tag are in
--    scope — journalist/byline mentions on the same articles are written by a
--    different producer and are untouched.
DELETE FROM shared.entity_mentions em
 USING _mp_tag_verdict v
 WHERE em.product      = 'wtf'
   AND em.content_type = 'article'
   AND em.entity_id    = v.entity_id
   AND em.content_id   = v.article_id::text
   AND v.verdict IS NULL;

-- 3. Purge the tags themselves.
DELETE FROM wtf.article_mp_tags t
 USING _mp_tag_verdict v
 WHERE v.article_id = t.article_id
   AND v.mp_id      = t.mp_id
   AND v.verdict IS NULL;

-- 4. Read paths filter on match_type; make that cheap.
CREATE INDEX IF NOT EXISTS idx_article_mp_tags_article_matchtype
    ON wtf.article_mp_tags (article_id, match_type);

-- New tables/columns must be readable by the app role (it does not connect as
-- the owner) — an index needs no grant, but re-assert the table grant so a
-- fresh environment cannot end up with a table the consumer cannot read.
GRANT SELECT ON wtf.article_mp_tags TO wtfuser;

COMMIT;
