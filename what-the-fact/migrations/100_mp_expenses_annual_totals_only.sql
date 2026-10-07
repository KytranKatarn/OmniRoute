-- 100: allow TOTALS-ONLY member-years in parliament.mp_expenses_annual (FY2002-FY2009 House reports).
--
-- The old (April 2001 - March 2009) annual tables print no per-member total and omit blank cells, so the category split is
-- ambiguous; only the SUM of a member's amounts is reliable (and each year's sum is checked against the report's own printed
-- Total row). Those rows store total_cad and leave the four category columns NULL — never a guessed split, never a fake 0.
-- Every existing FY2010-FY2015 row keeps its categories.
--
-- partial_year: only a row that CARRIES a status other than 'Active' is partial. Before, a NULL status read as partial; the old
-- tables give no status (FY2009 does, FY2002-FY2008 do not), so "unknown" must not be reported as "partial".
--
-- Re-runnable.

ALTER TABLE parliament.mp_expenses_annual ALTER COLUMN salaries_cad DROP NOT NULL;
ALTER TABLE parliament.mp_expenses_annual ALTER COLUMN travel_cad DROP NOT NULL;
ALTER TABLE parliament.mp_expenses_annual ALTER COLUMN hospitality_cad DROP NOT NULL;
ALTER TABLE parliament.mp_expenses_annual ALTER COLUMN contracts_cad DROP NOT NULL;

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
       (a.status IS NOT NULL AND a.status <> 'Active')                    AS partial_year,
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
        GRANT SELECT ON parliament.v_mp_expenses_annual_by_party TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('100', '100_mp_expenses_annual_totals_only.sql', 'Allow totals-only member-years (FY2002-FY2009 House annual reports); partial_year no longer true for an unknown status', now())
ON CONFLICT (version) DO NOTHING;
