-- 071: suppress live-stream / channel landing pages that are not articles.
--
-- WHAT THESE ARE
-- --------------
-- Two shapes, both from CTV/BNN feeds, both landing pages rather than stories:
--
--   `LIVE<n> Digital Channel - <publisher>`   177 visible, bodies 30-241 chars
--   `CTVNews - CTV News`                       35 visible, bodies ~25 chars
--
-- They are the publisher's 24/7 stream page, re-announced in the feed. There is no
-- story, no claim to check and no bias to measure — but they were counted as
-- articles, clustered, and fed to the analysis backlog like anything else.
--
-- New reason `non_article_stream`, distinct from `publisher_suffix_title` (a title
-- that is JUST the publisher, from a broken feed) and from `duplicate_refetch` (a
-- real story fetched twice). Keeping them apart matters: `duplicate_refetch` rows
-- have a survivor and 301; these have none and correctly 410 (migration 070's
-- route logic keys off `canonical_article_id`, which stays NULL here).
--
-- ⚠️ THE REGEX IS ANCHORED AND NARROW ON PURPOSE. An earlier pass at this used
-- `^LIVE[0-9]* Digital Channel$` and matched ZERO rows, because every real title
-- carries a publisher suffix (`LIVE1 Digital Channel - BNN Bloomberg`). That empty
-- result read as "already clean" and nearly closed the item. Verified live: the
-- anchored-with-suffix form matches exactly 177, the count measured independently.
--
-- Deliberately NOT included: radio programme titles ("Morning vibes with Bounce
-- 99.9", "Midi moins quart"). Those look similar but I cannot write a rule that
-- separates a recurring programme slot from a real segment without guessing, and a
-- wrong rule here silently deletes journalism. Left for a human call.
--
-- REVERSIBLE: UPDATE ... SET suppressed_reason = NULL WHERE suppressed_reason =
-- 'non_article_stream'. IDEMPOTENT: re-running matches nothing new.

BEGIN;

UPDATE wtf.articles
   SET suppressed_reason = 'non_article_stream'
 WHERE suppressed_reason IS NULL
   AND (    title ~ '^LIVE[0-9]* Digital Channel - '
         OR title = 'CTVNews - CTV News');

COMMIT;
