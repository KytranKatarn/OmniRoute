-- 094_mp_terms.sql — every MP stint since 2000 with its party, so a party switch is a dated fact.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY: parliament.mps holds ONE party per person (the current one) and only ~340 rows (the sitting
-- members). parliament.mp_movements only records changes seen since we started watching. Neither can
-- answer "which party carried this MP's costs in 2009" or "when did this MP cross the floor".
-- The House's own member list is no help either: it returns one record per person (their LATEST stint),
-- so earlier terms and switches are lost (measured 2026-10-06: 1,236 persons, 0 with a second record;
-- Chris d'Entremont's House profile shows only "Liberal"). openparliament.ca exposes DATED stints
-- instead, split on every party change, back to 1994:
--     Conservative  2019-10-21 .. 2025-04-28  West Nova
--     Conservative  2025-04-28 .. 2025-11-04  Acadie—Annapolis
--     Liberal       2025-11-05 ..             Acadie—Annapolis
--
-- CUTOFF: owner decision 2026-10-06 — nothing that ended before 2000-01-01 is stored.
-- Re-runnable: IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT.

CREATE TABLE IF NOT EXISTS parliament.mp_terms (
    id          bigserial   PRIMARY KEY,
    op_slug     text        NOT NULL,                 -- openparliament politician slug == parliament.mps.slug
    op_membership_id integer,                         -- openparliament membership id (stable)
    name        text        NOT NULL,
    mp_id       integer     REFERENCES parliament.mps(id) ON DELETE SET NULL,
    party       text,                                  -- short name: Liberal, Conservative, Bloc Québécois ...
    riding      text,
    province    text,
    start_date  date        NOT NULL,
    end_date    date,                                  -- NULL = still sitting in this stint
    source_url  text        NOT NULL,
    synced_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (op_slug, start_date, riding, party)
);
CREATE INDEX IF NOT EXISTS mp_terms_mp_idx    ON parliament.mp_terms (mp_id);
CREATE INDEX IF NOT EXISTS mp_terms_start_idx ON parliament.mp_terms (start_date);

-- A change of party = a stint whose party differs from that person's previous stint.
-- `changed_on` is the new stint's start date (for a floor-crossing, the day it took effect).
-- Gaps between stints (lost an election, then returned) still compare to the previous stint, so a
-- person who sat Liberal, was out for a term, and returned Conservative appears here too — filter on
-- `gap_days` (days between the previous stint's end and this start) to separate a crossing (small gap)
-- from a later return under another banner.
CREATE OR REPLACE VIEW parliament.v_mp_party_changes AS
SELECT op_slug, name, mp_id, from_party, to_party, changed_on, riding, gap_days
  FROM (
    SELECT op_slug, name, mp_id, riding,
           lag(party)    OVER w AS from_party,
           party                AS to_party,
           start_date           AS changed_on,
           (start_date - lag(end_date) OVER w) AS gap_days
      FROM parliament.mp_terms
    WINDOW w AS (PARTITION BY op_slug ORDER BY start_date, id)
  ) x
 WHERE from_party IS NOT NULL AND to_party IS NOT NULL AND from_party <> to_party;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.mp_terms TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.mp_terms_id_seq TO wtfuser;
        GRANT SELECT ON parliament.v_mp_party_changes TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('094', '094_mp_terms.sql', 'MP stints with dated party, 2000+, for party-switch tracking and cost attribution', now())
ON CONFLICT (version) DO NOTHING;
