-- 074_election_results.sql — Elections Canada general-election results
--
-- Feeds the newsroom rebuild's /races and /parties pages. Source is
-- open.canada.ca CKAN, org `elections`, "<n>th General Election: Official
-- Voting Results", Table 12 (candidates by district) — parsed by
-- ingest/elections/results_parse.py.
--
-- ⚠️ NOT elections.ca. That host's robots.txt returns HTTP 500, and RFC 9309
-- says a 5xx on robots.txt means assume COMPLETE DISALLOW. Some CKAN resources
-- (GE42's) point back there, so the ingest validates the resource HOST.
--
-- ⚠️ `elected` IS NOT DERIVED FROM THE `**` MARKER. Table 12 has no elected
-- column, and the `**` in the candidate cell marks the INCUMBENT, not the
-- winner: measured over GE44, 306 rows carry it, 32 districts have none at all,
-- and it identifies the top-vote row in only 285 of 338. The winner is the row
-- with a non-empty Majority — which agrees with "most votes" 338/338. Reading
-- `**` as victory names the WRONG MP in 53 ridings. KB mistake #301957.
--
-- `incumbent` is stored SEPARATELY because it is real, useful information —
-- just not the information it resembles.

CREATE TABLE IF NOT EXISTS parliament.elections (
    id              serial PRIMARY KEY,
    ge_number       integer NOT NULL UNIQUE,      -- 44 = 44th General Election
    election_date   date,
    -- CKAN dataset id, so a row can always be traced back to its source
    dataset_id      text,
    source_url      text,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE parliament.elections IS
  'One row per federal general election whose official results have been '
  'ingested from open.canada.ca CKAN (org: elections).';

CREATE TABLE IF NOT EXISTS parliament.election_candidates (
    id               bigserial PRIMARY KEY,
    election_id      integer NOT NULL REFERENCES parliament.elections(id) ON DELETE CASCADE,
    district_number  text NOT NULL,               -- e.g. '10001'; text, it is an identifier
    district_name    text,
    province         text,
    candidate_name   text NOT NULL,
    party            text,                        -- normalised English short form
    party_raw        text,                        -- the bilingual cell, kept verbatim
    incumbent        boolean NOT NULL DEFAULT false,  -- the ** marker. NOT "won".
    votes            integer NOT NULL DEFAULT 0,
    vote_share       numeric(5,2),
    majority         integer,                     -- non-NULL ONLY on the winner
    elected          boolean NOT NULL DEFAULT false,
    -- ⚠️ PARTY IS PART OF THE KEY, and it has to be. In GE43 the riding of
    -- Beauce (24007) fielded TWO candidates both named "Maxime Bernier": the
    -- People's Party leader (16,796 votes) and a Rhinoceros Party candidate who
    -- legally changed his name to confuse the ballot. A (district, name) key
    -- silently DROPPED one of them — 2,146 parsed, 2,145 stored, and the count
    -- was the only symptom. A person's name is not a unique identifier, and a
    -- Canadian ballot is a place where that gets exploited on purpose.
    UNIQUE (election_id, district_number, candidate_name, party)
);

COMMENT ON COLUMN parliament.election_candidates.incumbent IS
  'The ** marker in the source Candidate cell — a sitting MP who ran again. '
  'This is NOT the winner flag; see `elected`. KB mistake #301957.';
COMMENT ON COLUMN parliament.election_candidates.elected IS
  'Won the seat. Derived from a non-empty Majority in the source, cross-checked '
  'against highest votes (the two agree 338/338 in GE44). Never from **.';
COMMENT ON COLUMN parliament.election_candidates.majority IS
  'Winning margin. NULL for every non-winner — that emptiness is the source''s '
  'winner signal, not missing data.';

CREATE INDEX IF NOT EXISTS ix_elec_cand_district
    ON parliament.election_candidates (election_id, district_number);
-- /races and /parties both lead with "who won", so the winner lookup is the
-- hot path; partial keeps it to one row per district.
CREATE INDEX IF NOT EXISTS ix_elec_cand_winners
    ON parliament.election_candidates (election_id, district_number)
    WHERE elected;
CREATE INDEX IF NOT EXISTS ix_elec_cand_party
    ON parliament.election_candidates (election_id, party);

-- New objects must be granted to the app role or they are invisible at runtime:
-- apps do not connect as the owner, and a missing GRANT surfaces as a runtime
-- permission error rather than a migration failure (the migration-047 lesson).
--
-- ⚠️ FULL DML, NOT SELECT. The first draft granted SELECT only — copying
-- migration 073, which added a column the app READS. These tables are written
-- by an INGEST, so read-only grants fail at the first upsert with
-- "permission denied for table elections". Caught by running the ingest for
-- real: it parsed GE44 and GE43 perfectly (338/338 winners each) and then could
-- not write a row.
--
-- ALL matches every sibling in this schema — parliament.mps, mp_votes,
-- ec_contributions and ingest_log all grant the full set to wtfuser. A table
-- whose permissions differ from its neighbours is a trap for whoever touches it
-- next; these hold published public data with nothing sensitive in them.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.elections TO wtfuser;
        GRANT ALL ON parliament.election_candidates TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.elections_id_seq TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.election_candidates_id_seq TO wtfuser;
    END IF;
END $$;
