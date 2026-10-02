-- 086_elections_complete.sql — completes the /elections data model (builds on 085).
--
-- Everything here follows 085's rule: CURATED data is hidden until a human has verified
-- it against a source. Nothing in this migration inserts a date, a result or an office-
-- holder; it adds the places they will live and seeds only NAMES.
--
-- 1. election_calendar gains municipal rows + who-governs columns.
-- 2. parliament.election_history holds past results for non-federal jurisdictions
--    (federal history is DERIVED from parliament.election_candidates — never stored twice).
-- 3. Municipal calendar rows are seeded UNVERIFIED for the 25 cities the site already
--    tracks (shared/city_identity.CANONICAL_CITIES); dates come later via
--    scripts/elections_admin.py, which refuses a row without a source URL.

ALTER TABLE parliament.election_calendar DROP CONSTRAINT IF EXISTS election_calendar_level_check;
ALTER TABLE parliament.election_calendar
    ADD CONSTRAINT election_calendar_level_check
    CHECK (level IN ('federal', 'provincial', 'municipal'));

-- Who governs. Verified together with the dates (same verified_at gate): an office-holder
-- is a fact that goes stale on a resignation, so it is never shown unverified.
ALTER TABLE parliament.election_calendar ADD COLUMN IF NOT EXISTS government_party text;
ALTER TABLE parliament.election_calendar ADD COLUMN IF NOT EXISTS head_of_government text;
-- Municipal rows name their province so the page can group them.
ALTER TABLE parliament.election_calendar ADD COLUMN IF NOT EXISTS province_code text;

CREATE TABLE IF NOT EXISTS parliament.election_history (
    id              serial PRIMARY KEY,
    jurisdiction_code text NOT NULL,          -- matches election_calendar.jurisdiction_code
    election_date   date NOT NULL,
    turnout_pct     numeric(5,2),
    seats_total     integer,
    -- [{"party": "Liberal", "seats": 160, "votes": 5556629}, ...]; votes optional.
    results         jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_url      text NOT NULL CHECK (source_url <> ''),   -- no source, no row
    verified_at     timestamptz NOT NULL DEFAULT now(),       -- only ever written verified
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (jurisdiction_code, election_date)
);
CREATE INDEX IF NOT EXISTS ix_election_history_jur
    ON parliament.election_history (jurisdiction_code, election_date DESC);

-- Municipal seeds: NAMES ONLY (dates/rules/source/verified_at stay NULL).
INSERT INTO parliament.election_calendar (jurisdiction_code, jurisdiction, level, province_code) VALUES
    ('MUN-calgary','Calgary','municipal','AB'),('MUN-edmonton','Edmonton','municipal','AB'),
    ('MUN-kelowna','Kelowna','municipal','BC'),('MUN-vancouver','Vancouver','municipal','BC'),
    ('MUN-victoria','Victoria','municipal','BC'),('MUN-winnipeg','Winnipeg','municipal','MB'),
    ('MUN-fredericton','Fredericton','municipal','NB'),('MUN-moncton','Moncton','municipal','NB'),
    ('MUN-saint-john','Saint John','municipal','NB'),('MUN-st-johns','St. John''s','municipal','NL'),
    ('MUN-halifax','Halifax','municipal','NS'),('MUN-sydney','Sydney','municipal','NS'),
    ('MUN-yellowknife','Yellowknife','municipal','NT'),('MUN-iqaluit','Iqaluit','municipal','NU'),
    ('MUN-hamilton','Hamilton','municipal','ON'),('MUN-london','London','municipal','ON'),
    ('MUN-ottawa','Ottawa','municipal','ON'),('MUN-toronto','Toronto','municipal','ON'),
    ('MUN-windsor','Windsor','municipal','ON'),('MUN-charlottetown','Charlottetown','municipal','PE'),
    ('MUN-montreal','Montréal','municipal','QC'),('MUN-quebec','Québec','municipal','QC'),
    ('MUN-regina','Regina','municipal','SK'),('MUN-saskatoon','Saskatoon','municipal','SK'),
    ('MUN-whitehorse','Whitehorse','municipal','YT')
ON CONFLICT (jurisdiction_code) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.election_calendar TO wtfuser;
        GRANT ALL ON parliament.election_history TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.election_history_id_seq TO wtfuser;
    END IF;
END $$;
