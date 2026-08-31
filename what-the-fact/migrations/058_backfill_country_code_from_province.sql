-- 058 — backfill articles.country_code from province_code (#6210)
--
-- WHY
-- extract_geo() did `result.setdefault("country_code", "CA")` on a dict that
-- had already been through _sanitize(). Sanitize converts the LLM's literal
-- "null" into a real Python None, which leaves the KEY PRESENT — and
-- setdefault only fills a MISSING key. The default was therefore a silent
-- no-op for every article L.O.C.A.L. geocoded to a Canadian province.
--
-- Measured before this migration: 21 consecutive days with ZERO country_code
-- written, ~150-800 geocoded articles per day; 4,460 provincial articles in
-- one week of which exactly ONE had a country. /map colours pins by country,
-- so every pin rendered the same "unknown" grey while the legend advertised
-- Canadian and International categories that could never appear.
--
-- The code fix (ingest/geocoder.py, _fill_if_blank) stops the bleeding for NEW
-- articles. This migration recovers the ones already written.
--
-- WHY THIS IS SOUND, NOT A GUESS
-- A valid Canadian province code IS a statement about the country: Ontario is
-- in Canada definitionally. We are not inferring a country from weak evidence,
-- we are propagating one the row already carries.
--
-- ⚠️ TWO GUARDS, BOTH LOAD-BEARING:
--
--  1. `country_code IS NULL` — a REPORTED country always wins. There are live
--     rows with country_code='US' AND province_code='ON'; overwriting those
--     would relabel American articles Canadian. Restricting to NULL also makes
--     this migration idempotent: re-running it touches nothing.
--
--  2. The explicit 13-code allowlist — province_code is NOT exclusively
--     Canadian in this table. It also holds US state codes ('KY', 'NY') and at
--     least one row carries 'CA', a COUNTRY code sitting in the province
--     column. `province_code IS NOT NULL` would file Kentucky under Canada.
--
-- REVERSIBILITY
-- Deliberately NOT reversible as written: once set, these rows are
-- indistinguishable from rows the fixed geocoder writes, which is the intent.
-- To undo, restore from the nightly dump — see .claude/rules/backup-manager.md.

BEGIN;

UPDATE wtf.articles
   SET country_code = 'CA'
 WHERE country_code IS NULL
   AND province_code IN ('AB','BC','MB','NB','NL','NS','NT','NU',
                         'ON','PE','QC','SK','YT');

-- Report what could NOT be recovered, so the residue is visible rather than
-- quietly assumed away. These have no province either, so nothing at the data
-- layer can place them; they stay honestly NULL and /map keeps showing them as
-- "country not resolved".
DO $$
DECLARE
  fixed   bigint;
  residue bigint;
BEGIN
  SELECT count(*) INTO fixed
    FROM wtf.articles WHERE country_code = 'CA';
  SELECT count(*) INTO residue
    FROM wtf.articles WHERE country_code IS NULL;
  RAISE NOTICE '058: rows now CA=%, still-unresolved=%', fixed, residue;
END $$;

COMMIT;
