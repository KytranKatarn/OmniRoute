-- 095_mp_expenses_by_party.sql — what each party's MPs cost, attributed by the party in force AT THE TIME.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- Depends on 094 (parliament.mp_terms). Before this, parliament.mps.party held ONE party per person (the
-- current one), so an MP who crossed the floor would carry all of their history under the new party.
--
-- RULES (explicit, because every one of them moves a number):
--  * An expense period 'YYYY-Qn' (n = FISCAL quarter; Q1=Apr, Q2=Jul, Q3=Oct, Q4=Jan of that calendar year) is
--    attributed to the party whose stint covers the quarter's MIDPOINT (start + 45 days).
--  * `party_changed_in_quarter` is TRUE when a different-party stint begins inside the quarter, so a split
--    quarter is visible rather than silently assigned to one side.
--  * An expense with no covering stint is reported as 'Unattributed', never dropped — totals must reconcile
--    with parliament.mp_expenses.
--  * RETIRED MPs are included (sitting = false). Their costs belong to the party that carried them.
--  * Independents and unaffiliated members are their own bucket ('Independent' / as published).
--
-- Re-runnable: CREATE OR REPLACE VIEW.

CREATE OR REPLACE VIEW parliament.v_mp_expenses_by_party AS
SELECT e.id              AS expense_id,
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
       e.travel_cad, e.hospitality_cad, e.contracts_cad, e.salaries_cad, e.total_cad
  FROM parliament.mp_expenses e
  JOIN parliament.mps m ON m.id = e.mp_id
 CROSS JOIN LATERAL (
        SELECT make_date(split_part(e.period, '-Q', 1)::int,
                         CASE split_part(e.period, '-Q', 2) WHEN '1' THEN 4 WHEN '2' THEN 7 WHEN '3' THEN 10 ELSE 1 END,
                         1) AS q_start) s
  LEFT JOIN LATERAL (
        SELECT t0.party FROM parliament.mp_terms t0
         WHERE t0.mp_id = e.mp_id
           AND t0.start_date <= (s.q_start + 45)
           AND (t0.end_date IS NULL OR t0.end_date >= (s.q_start + 45))
         ORDER BY t0.start_date DESC LIMIT 1) t ON true
 WHERE e.period ~ '^[0-9]{4}-Q[1-4]$';

-- One row per party per calendar year, sitting and retired members shown separately.
CREATE OR REPLACE VIEW parliament.v_party_mp_costs_by_year AS
SELECT extract(year FROM q_start)::int AS year,
       party,
       count(DISTINCT mp_id)                                        AS mps,
       count(DISTINCT mp_id) FILTER (WHERE NOT sitting)             AS retired_mps,
       round(sum(salaries_cad), 2)                                  AS salaries_cad,
       round(sum(travel_cad), 2)                                    AS travel_cad,
       round(sum(hospitality_cad), 2)                               AS hospitality_cad,
       round(sum(contracts_cad), 2)                                 AS contracts_cad,
       round(sum(total_cad), 2)                                     AS total_cad,
       round(sum(total_cad) FILTER (WHERE NOT sitting), 2)          AS total_cad_retired,
       count(*) FILTER (WHERE party_changed_in_quarter)             AS split_quarters
  FROM parliament.v_mp_expenses_by_party
 GROUP BY 1, 2;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT ON parliament.v_mp_expenses_by_party, parliament.v_party_mp_costs_by_year TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('095', '095_mp_expenses_by_party.sql', 'MP expenses attributed to the party in force at the time (incl. retired MPs)', now())
ON CONFLICT (version) DO NOTHING;
