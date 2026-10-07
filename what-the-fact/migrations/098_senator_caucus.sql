-- 098_senator_caucus.sql — which Senate caucus a senator belonged to, quarter by quarter, from 2016-Q3.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY: parliament.senators.caucus is ONE current value, so a senator who moved (Robert Black: ISG 2018Q1 -> CSG 2019Q3;
-- Michele Audette: ISG -> PSG -> Non-affiliated -> PSG) carried their whole history under the newest group, and a
-- former senator under whatever they last held. Wikidata cannot fix it: 36 of 1,052 party statements are dated, and they are
-- lifetime PARTY memberships, not Senate groups. The Senate's own quarterly expense summaries list each senator's
-- affiliation for THAT quarter (probed 2026-10-07: 40 quarters, 195 senators, 9 labels, 92 senators who changed), and
-- the expense sync already visits every one of those rows — so the history is captured there, at no extra requests.
--
-- LIMIT: 2016-Q3 is as far back as the Senate publishes these summaries. No dated source was found for 2000-2016.
--
-- Periods use the Senate's CALENDAR quarters ('2018-Q1' = Jan-Mar), the same labels as senator_expenses and
-- senate_travel_trips — unlike the House's fiscal labels in mp_expenses.
-- Re-runnable: IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT.

CREATE TABLE IF NOT EXISTS parliament.senator_caucus_quarters (
    id          bigserial   PRIMARY KEY,
    senator_id  integer     NOT NULL REFERENCES parliament.senators(id) ON DELETE CASCADE,
    period      text        NOT NULL,                 -- '2018-Q1' (calendar quarter)
    q_start     date        NOT NULL,
    caucus      text        NOT NULL,                 -- as published: 'Independent Senators Group', 'Conservative Party of Canada' ...
    caucus_short text,                                -- ISG / Conservative / CSG / PSG / Non-affiliated / Liberal ...
    source_url  text,
    synced_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (senator_id, period)
);
CREATE INDEX IF NOT EXISTS senator_caucus_quarters_start_idx ON parliament.senator_caucus_quarters (q_start);

-- A change = a quarter whose caucus differs from that senator's previous recorded quarter.
-- `quarters_between` > 1 means quarters are missing between the two observations (the senator was not on the summary, or
-- a report is not loaded) — the move happened somewhere in that window, not necessarily in `changed_in`.
CREATE OR REPLACE VIEW parliament.v_senator_caucus_changes AS
SELECT senator_id, from_caucus, to_caucus, changed_in, quarters_between
  FROM (
    SELECT senator_id,
           lag(coalesce(caucus_short, caucus)) OVER w AS from_caucus,
           coalesce(caucus_short, caucus)              AS to_caucus,
           period                                      AS changed_in,
           ((extract(year FROM q_start) * 4 + extract(month FROM q_start) / 3)
            - lag(extract(year FROM q_start) * 4 + extract(month FROM q_start) / 3) OVER w)::int AS quarters_between
      FROM parliament.senator_caucus_quarters
    WINDOW w AS (PARTITION BY senator_id ORDER BY q_start)
  ) x
 WHERE from_caucus IS NOT NULL AND from_caucus <> to_caucus;

-- Expenses attributed to the caucus the senator held IN THAT QUARTER. A quarter with no caucus row is 'Unattributed'
-- (never dropped), so totals reconcile with parliament.senator_expenses.
CREATE OR REPLACE VIEW parliament.v_senator_expenses_by_caucus AS
SELECT e.id AS expense_id, e.senator_id, s.name AS senator_name, s.is_current AS sitting, e.period,
       make_date(split_part(e.period, '-Q', 1)::int, (split_part(e.period, '-Q', 2)::int - 1) * 3 + 1, 1) AS q_start,
       COALESCE(c.caucus_short, c.caucus, 'Unattributed') AS caucus,
       e.travel_cad, e.hospitality_cad, e.contracts_cad, e.office_cad, e.living_cad, e.total_cad
  FROM parliament.senator_expenses e
  JOIN parliament.senators s ON s.id = e.senator_id
  LEFT JOIN parliament.senator_caucus_quarters c ON c.senator_id = e.senator_id AND c.period = e.period
 WHERE e.period ~ '^[0-9]{4}-Q[1-4]$';

CREATE OR REPLACE VIEW parliament.v_caucus_senate_costs_by_year AS
SELECT extract(year FROM q_start)::int AS year,
       caucus,
       count(DISTINCT senator_id)                                AS senators,
       count(DISTINCT senator_id) FILTER (WHERE NOT sitting)     AS former_senators,
       round(sum(travel_cad), 2)                                 AS travel_cad,
       round(sum(total_cad), 2)                                  AS total_cad,
       round(sum(total_cad) FILTER (WHERE NOT sitting), 2)       AS total_cad_former
  FROM parliament.v_senator_expenses_by_caucus
 GROUP BY 1, 2;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.senator_caucus_quarters TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.senator_caucus_quarters_id_seq TO wtfuser;
        GRANT SELECT ON parliament.v_senator_caucus_changes, parliament.v_senator_expenses_by_caucus,
                        parliament.v_caucus_senate_costs_by_year TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('098', '098_senator_caucus.sql', 'Senators caucus by quarter (2016-Q3+) from the Senate expense summaries; changes + expenses-by-caucus views', now())
ON CONFLICT (version) DO NOTHING;
