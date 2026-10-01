-- 085_election_calendar.sql — curated election calendar for /elections.
--
-- ⚠️ EVERY ROW IS SEEDED UNVERIFIED (verified_at NULL). The seed values come from
-- the Claude Design prototype (design-handoff/wtf-elections.js), which is a
-- design reading, not a checked source — and at least one of its dates disagrees
-- with an independent recollection (Nunavut/NWT terms), which is exactly why
-- nothing is shown until a human checks it. The page WITHHOLDS the date of any
-- row where verified_at IS NULL (shared/election_calendar.py).
--
-- To verify a row (after reading the statute / the election agency's page):
--   UPDATE parliament.election_calendar
--      SET last_election = '<date>', next_latest_date = '<date>',
--          rule = '<statute + section, in words>', source_url = '<url>',
--          verified_at = now()
--    WHERE jurisdiction_code = '<code>';
-- After an election is held, roll the row forward the same way. The daily drift
-- guard alarms on: any unverified row, a passed next_latest_date, and a
-- verification older than 180 days.
--
-- Municipal is NOT here yet (planned: major cities already covered by the site).

CREATE TABLE IF NOT EXISTS parliament.election_calendar (
    jurisdiction_code text PRIMARY KEY,           -- 'CA' or 2-letter province/territory
    jurisdiction      text NOT NULL,
    level             text NOT NULL CHECK (level IN ('federal', 'provincial')),
    last_election     date,
    next_latest_date  date,                       -- latest LEGAL date (fixed-date rule); a snap election can come earlier
    rule              text,
    source_url        text,
    verified_at       timestamptz,                -- NULL = unverified, date withheld on the page
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- Unverified seed: dates deliberately NOT inserted. The prototype values are kept
-- here as a comment so the verifier knows what to check against:
--   CA 2025-04-28 / 2029-10-15 · QC 2022-10-03 / 2026-10-05 · AB 2023-05-29 / 2027-10-18
--   MB 2023-10-03 / 2027-10-05 · PE 2023-04-03 / 2027-10-04 · NT 2023-11-14 / 2027-11-15
--   BC 2024-10-19 / 2028-10-21 · SK 2024-10-28 / 2028-10-30 · NB 2024-10-21 / 2028-10-16
--   NS 2024-11-26 / 2028-07-15 · ON 2025-02-27 / 2029-06-07 · NL 2025-10-14 / 2029-10-09
--   YT 2025-11-03 / 2029-11-03 · NU 2025-10-27 / 2029-10-29
INSERT INTO parliament.election_calendar (jurisdiction_code, jurisdiction, level) VALUES
    ('CA', 'Canada (federal)',        'federal'),
    ('QC', 'Québec',                   'provincial'),
    ('AB', 'Alberta',                  'provincial'),
    ('MB', 'Manitoba',                 'provincial'),
    ('PE', 'Prince Edward Island',     'provincial'),
    ('NT', 'Northwest Territories',    'provincial'),
    ('BC', 'British Columbia',         'provincial'),
    ('SK', 'Saskatchewan',             'provincial'),
    ('NB', 'New Brunswick',            'provincial'),
    ('NS', 'Nova Scotia',              'provincial'),
    ('ON', 'Ontario',                  'provincial'),
    ('NL', 'Newfoundland and Labrador','provincial'),
    ('YT', 'Yukon',                    'provincial'),
    ('NU', 'Nunavut',                  'provincial')
ON CONFLICT (jurisdiction_code) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.election_calendar TO wtfuser;
    END IF;
END $$;
