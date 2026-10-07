-- 097_mp_expenses_archive.sql — MP expenses Apr 2014 -> Mar 2020 from the House's per-member archive.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- The current House site only serves per-member data from FY2021 Q2; parliament.mp_expenses therefore starts at
-- 2020-Q2. The archive reports are fiscal YEAR-TO-DATE, so they are stored as YTD and DIFFERENCED here; a quarter whose
-- predecessor report is missing is left out rather than guessed. Categories are folded to the same four as
-- parliament.mp_expenses (see ingest/parliament/mp_expenses_archive.py for the mapping and why it is comparable).
--
-- Also redefines parliament.v_mp_expenses_by_party (095/096) over BOTH sources, appending a `source` column. The party
-- rule is unchanged: covering stint at the quarter midpoint, else the latest earlier stint ('wind_down').
--
-- Re-runnable: IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT.

CREATE TABLE IF NOT EXISTS parliament.mp_expenses_archive (
    id                   bigserial     PRIMARY KEY,
    mp_id                integer       NOT NULL REFERENCES parliament.mps(id) ON DELETE CASCADE,
    fiscal_year          integer       NOT NULL,           -- FY2019 = Apr 2018 .. Mar 2019
    fq                   integer       NOT NULL CHECK (fq BETWEEN 1 AND 4),
    period               text          NOT NULL,           -- same label scheme as mp_expenses ('2018-Q1' .. '2019-Q4')
    period_end           date          NOT NULL,
    status               text,                             -- Active / NR / NE / DE / RS ...
    constituency         text,
    caucus               text,                             -- party AS PUBLISHED for that quarter
    ytd_salaries_cad     numeric(14,2),
    ytd_travel_cad       numeric(14,2),
    ytd_hospitality_cad  numeric(14,2),
    ytd_contracts_cad    numeric(14,2),
    ytd_total_cad        numeric(14,2),
    ytd_detail           jsonb,                            -- the eight raw categories {"1": salaries .. "8": offices}
    source_code          text          NOT NULL,
    source_url           text          NOT NULL,
    synced_at            timestamptz   NOT NULL DEFAULT now(),
    UNIQUE (mp_id, fiscal_year, fq)
);
CREATE INDEX IF NOT EXISTS mp_expenses_archive_period_idx ON parliament.mp_expenses_archive (fiscal_year, fq);

-- Quarterly amounts = YTD minus the previous quarter's YTD.
--  * fq = 1: the YTD IS the quarter.
--  * fq > 1 and the MP has the previous quarter: difference.
--  * fq > 1, the previous quarter's REPORT is loaded but this MP is not in it: they were not a member then (newly
--    elected / by-election), so the YTD is entirely this quarter.
--  * fq > 1 and the previous quarter's report is not loaded at all: NOT derivable — row omitted.
CREATE OR REPLACE VIEW parliament.v_mp_expenses_archive_quarterly AS
SELECT a.id, a.mp_id, a.period, a.fiscal_year, a.fq,
       a.ytd_salaries_cad    - COALESCE(p.ytd_salaries_cad, 0)    AS salaries_cad,
       a.ytd_travel_cad      - COALESCE(p.ytd_travel_cad, 0)      AS travel_cad,
       a.ytd_hospitality_cad - COALESCE(p.ytd_hospitality_cad, 0) AS hospitality_cad,
       a.ytd_contracts_cad   - COALESCE(p.ytd_contracts_cad, 0)   AS contracts_cad,
       a.ytd_total_cad       - COALESCE(p.ytd_total_cad, 0)       AS total_cad,
       a.status, a.caucus
  FROM parliament.mp_expenses_archive a
  LEFT JOIN parliament.mp_expenses_archive p
         ON p.mp_id = a.mp_id AND p.fiscal_year = a.fiscal_year AND p.fq = a.fq - 1
 WHERE a.fq = 1
    OR p.id IS NOT NULL
    OR EXISTS (SELECT 1 FROM parliament.mp_expenses_archive r
                WHERE r.fiscal_year = a.fiscal_year AND r.fq = a.fq - 1);

CREATE OR REPLACE VIEW parliament.v_mp_expenses_by_party AS
WITH exp AS (
    SELECT id AS expense_id, mp_id, period, travel_cad, hospitality_cad, contracts_cad, salaries_cad, total_cad,
           'house_site'::text AS source
      FROM parliament.mp_expenses
    UNION ALL
    SELECT (-id)::integer AS expense_id, mp_id, period,
           travel_cad::numeric(12,2), hospitality_cad::numeric(12,2), contracts_cad::numeric(12,2),
           salaries_cad::numeric(12,2), total_cad::numeric(12,2),
           'house_archive'::text
      FROM parliament.v_mp_expenses_archive_quarterly
)
SELECT e.expense_id,
       e.mp_id,
       m.name            AS mp_name,
       m.is_current      AS sitting,
       e.period,
       s.q_start,
       COALESCE(t.party, 'Unattributed') AS party,
       EXISTS (SELECT 1 FROM parliament.mp_terms x
                WHERE x.mp_id = e.mp_id
                  AND x.start_date > s.q_start AND x.start_date <= (s.q_start + 91)
                  AND x.party IS DISTINCT FROM t.party)              AS party_changed_in_quarter,
       e.travel_cad, e.hospitality_cad, e.contracts_cad, e.salaries_cad, e.total_cad,
       CASE WHEN t.party IS NULL THEN 'none'
            WHEN t.covers      THEN 'in_term'
            ELSE 'wind_down' END                                      AS attribution,
       e.source
  FROM exp e
  JOIN parliament.mps m ON m.id = e.mp_id
 CROSS JOIN LATERAL (
        SELECT make_date(split_part(e.period, '-Q', 1)::int,
                         CASE split_part(e.period, '-Q', 2) WHEN '1' THEN 4 WHEN '2' THEN 7 WHEN '3' THEN 10 ELSE 1 END,
                         1) AS q_start) s
  LEFT JOIN LATERAL (
        SELECT t0.party,
               (t0.end_date IS NULL OR t0.end_date >= (s.q_start + 45)) AS covers
          FROM parliament.mp_terms t0
         WHERE t0.mp_id = e.mp_id
           AND t0.start_date <= (s.q_start + 45)
         ORDER BY (t0.end_date IS NULL OR t0.end_date >= (s.q_start + 45)) DESC, t0.start_date DESC
         LIMIT 1) t ON true
 WHERE e.period ~ '^[0-9]{4}-Q[1-4]$';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.mp_expenses_archive TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.mp_expenses_archive_id_seq TO wtfuser;
        GRANT SELECT ON parliament.v_mp_expenses_archive_quarterly, parliament.v_mp_expenses_by_party TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('097', '097_mp_expenses_archive.sql', 'MP expenses FY2015-FY2020 from the House archive (YTD stored, quarters derived); party view spans both sources', now())
ON CONFLICT (version) DO NOTHING;
