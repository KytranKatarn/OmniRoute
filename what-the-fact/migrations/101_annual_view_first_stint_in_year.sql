-- 101: parliament.v_mp_expenses_annual_by_party — a member who FIRST sat part-way through the year is not "Unattributed".
--
-- The view charges a member-year to the party of the stint covering the fiscal year's midpoint (period_start + 182). A member
-- elected that year has no stint at the midpoint when their first term is recorded from the day Parliament OPENED, not the election
-- (June 2004 election -> term from 4 Oct 2004, midpoint 30 Sep 2004). After the FY2002-FY2009 load, 106 of 403 FY2005 member-years,
-- 68 of 374 in FY2006 and 66 of 373 in FY2009 came out 'Unattributed', and — because NULL IS DISTINCT FROM <any party> — all of them
-- were also flagged party_changed_in_year (the page said 275 mid-year changers; the real figure is ~26).
--
-- Fix: when no stint begins on or before the midpoint, use the EARLIEST stint that begins within the year or up to 30 days after it
-- (FY2006: Jan 2006 election, Parliament opened 3 Apr 2006 = 3 days after the year ended). Labelled attribution = 'first_in_year' so a
-- reader/query can tell it from a midpoint match. A member with no stint in that window stays 'Unattributed' — never guessed.
-- Rows that already had a midpoint stint are unchanged. Re-runnable (CREATE OR REPLACE; same columns, same order).

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
            WHEN t.tier = 2      THEN 'first_in_year'
            WHEN t.covers        THEN 'in_term'
            ELSE 'wind_down' END                                          AS attribution,
       (a.status IS NOT NULL AND a.status <> 'Active')                    AS partial_year,
       a.status,
       a.salaries_cad, a.travel_cad, a.hospitality_cad, a.contracts_cad, a.total_cad
  FROM parliament.mp_expenses_annual a
  JOIN parliament.mps m ON m.id = a.mp_id
  LEFT JOIN LATERAL (
        SELECT x.party, x.covers, x.tier
          FROM (
                SELECT t0.party,
                       (t0.end_date IS NULL OR t0.end_date >= (a.period_start + 182)) AS covers,
                       1 AS tier, t0.start_date
                  FROM parliament.mp_terms t0
                 WHERE t0.mp_id = a.mp_id AND t0.start_date <= (a.period_start + 182)
                UNION ALL
                SELECT t0.party, true AS covers, 2 AS tier, t0.start_date
                  FROM parliament.mp_terms t0
                 WHERE t0.mp_id = a.mp_id
                   AND t0.start_date >  (a.period_start + 182)
                   AND t0.start_date <= (a.period_end + 30)
               ) x
         ORDER BY x.tier,
                  x.covers DESC,
                  CASE WHEN x.tier = 1 THEN x.start_date END DESC,
                  CASE WHEN x.tier = 2 THEN x.start_date END ASC
         LIMIT 1) t ON true;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT ON parliament.v_mp_expenses_annual_by_party TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('101', '101_annual_view_first_stint_in_year.sql', 'Annual expenses view: a member first sitting part-way through the year is attributed to that first stint, not Unattributed', now())
ON CONFLICT (version) DO NOTHING;
