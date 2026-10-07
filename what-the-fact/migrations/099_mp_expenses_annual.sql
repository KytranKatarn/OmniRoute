-- 099_mp_expenses_annual.sql — MP expenses for FY2009-10 .. FY2014-15 from the House's ANNUAL per-member reports.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY A SEPARATE TABLE: these reports give ONE figure per member for the whole fiscal year (Apr 1 - Mar 31). A year cannot be
-- split into quarters without inventing numbers, so it is NOT mixed into parliament.mp_expenses / mp_expenses_archive; it is
-- shown as fiscal years. fiscal_year is the year the FY ENDS (FY2010 = Apr 2009 .. Mar 2010), as in mp_expenses_archive.
--
-- Categories are folded to the same four as the quarterly series: salaries = cat 1, travel = cat 2, hospitality = cat 3,
-- contracts = cats 4+5+6 (advertising, printing, offices — the House's "all other expenses"). The raw lines are kept in
-- `detail`. total_cad is the PRINTED total (member's budget + resources provided by the House); the loader rejects any page
-- whose categories do not sum to it.
--
-- PARTY ATTRIBUTION (view below) follows the quarterly rule at fiscal-year granularity: the party the MP sat for at the
-- MIDPOINT of the fiscal year (Oct 1), else the latest earlier stint ('wind_down'), else 'Unattributed'. A member who changed
-- party during the year is flagged (party_changed_in_year) — the whole year is charged to ONE party, which is the honest limit
-- of annual data. `partial_year` marks members who did not serve the whole year (status other than 'Active').
--
-- Re-runnable: IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT.

CREATE TABLE IF NOT EXISTS parliament.mp_expenses_annual (
    id                bigserial     PRIMARY KEY,
    mp_id             integer       NOT NULL REFERENCES parliament.mps(id) ON DELETE CASCADE,
    fiscal_year       integer       NOT NULL,
    period_start      date          NOT NULL,
    period_end        date          NOT NULL,
    name_as_published text,
    status            text,                           -- Active / NR / NE / NSR / RS / DE / NEB ...
    constituency      text,
    caucus            text,                           -- party AS PUBLISHED in the report's member list
    salaries_cad      numeric(14,2) NOT NULL,
    travel_cad        numeric(14,2) NOT NULL,
    hospitality_cad   numeric(14,2) NOT NULL,
    contracts_cad     numeric(14,2) NOT NULL,
    total_cad         numeric(14,2) NOT NULL,
    detail            jsonb,                          -- {"1": [{line, cad}], "2": [...], ... "6": [...]}
    source_code       text          NOT NULL,
    source_url        text          NOT NULL,
    synced_at         timestamptz   NOT NULL DEFAULT now(),
    UNIQUE (mp_id, fiscal_year)
);
CREATE INDEX IF NOT EXISTS mp_expenses_annual_fy_idx ON parliament.mp_expenses_annual (fiscal_year);

CREATE OR REPLACE VIEW parliament.v_mp_expenses_annual_by_party AS
SELECT a.id AS annual_id,
       a.mp_id,
       m.name                     AS mp_name,
       m.is_current               AS sitting,
       a.fiscal_year,
       a.period_start             AS fy_start,
       a.period_end               AS fy_end,
       COALESCE(t.party, 'Unattributed') AS party,
       EXISTS (SELECT 1 FROM parliament.mp_terms x
                WHERE x.mp_id = a.mp_id
                  AND x.start_date > a.period_start AND x.start_date <= a.period_end
                  AND x.party IS DISTINCT FROM t.party)                  AS party_changed_in_year,
       CASE WHEN t.party IS NULL THEN 'none'
            WHEN t.covers      THEN 'in_term'
            ELSE 'wind_down' END                                          AS attribution,
       (a.status IS DISTINCT FROM 'Active')                               AS partial_year,
       a.status,
       a.salaries_cad, a.travel_cad, a.hospitality_cad, a.contracts_cad, a.total_cad
  FROM parliament.mp_expenses_annual a
  JOIN parliament.mps m ON m.id = a.mp_id
  LEFT JOIN LATERAL (
        SELECT t0.party,
               (t0.end_date IS NULL OR t0.end_date >= (a.period_start + 182)) AS covers
          FROM parliament.mp_terms t0
         WHERE t0.mp_id = a.mp_id
           AND t0.start_date <= (a.period_start + 182)
         ORDER BY (t0.end_date IS NULL OR t0.end_date >= (a.period_start + 182)) DESC, t0.start_date DESC
         LIMIT 1) t ON true;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.mp_expenses_annual TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.mp_expenses_annual_id_seq TO wtfuser;
        GRANT SELECT ON parliament.v_mp_expenses_annual_by_party TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('099', '099_mp_expenses_annual.sql', 'MP expenses FY2010-FY2015 from the House annual reports (one row per member-year) + party-attributed view', now())
ON CONFLICT (version) DO NOTHING;
