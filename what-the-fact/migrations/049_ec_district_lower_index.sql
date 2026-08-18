-- 049: functional index for the /mp/<slug> donor rollups.
--
-- mp_profile filters parliament.ec_contributions (7.3M rows / 1.8 GB) by
-- riding with a case-insensitive EXACT match. The old `electoral_district
-- ILIKE :riding` predicate could not use the btree ix_ec_district, so every
-- MP page paid two full parallel seq scans (~24s combined) — under any
-- concurrency the render crossed the ~30s ingress timeout and the page
-- surfaced as a 504/blank ("won't populate", 2026-08-18).
--
-- The queries now use lower(electoral_district) = lower(:riding); this
-- functional index serves them (verified: Bitmap Index Scan, cost
-- 254,030 -> 403).
--
-- Applied to the live hub `wtf` DB on 2026-08-18 with CREATE INDEX
-- CONCURRENTLY (no write lock). The plain form below is for fresh installs;
-- it takes a brief write lock while building (~1 min on the full table).
-- No GRANTs needed: indexes carry no ACLs (table owner is wtfuser).

CREATE INDEX IF NOT EXISTS ix_ec_district_lower
    ON parliament.ec_contributions (lower(electoral_district));
