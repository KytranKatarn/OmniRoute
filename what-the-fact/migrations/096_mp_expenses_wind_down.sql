-- 096_mp_expenses_wind_down.sql — costs an MP incurs AFTER leaving office belong to the party that carried them.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- Found on the first live run of 095 (2026-10-07): 726 expense rows ($10.9M) were 'Unattributed', 113 of them
-- for 2025-Q1 (Apr-Jun 2025). They are MPs who left at the 28 Apr 2025 election (Alghabra, Angus, Arya, Ashton ...):
-- the House still processes their office wind-down (staff severance, lease close-out) after their stint ended, so no
-- stint COVERS the quarter midpoint. Those costs are real and belong to the party the MP last sat for.
--
-- RULE (replaces 095's): attribute to the stint covering the quarter midpoint; if none, to the MP's MOST RECENT
-- stint that started before it. `attribution` says which ('in_term' | 'wind_down'). 'Unattributed' now means an MP
-- with no earlier stint at all. Columns are only APPENDED, so 095's consumers are unaffected.
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
       e.travel_cad, e.hospitality_cad, e.contracts_cad, e.salaries_cad, e.total_cad,
       CASE WHEN t.party IS NULL THEN 'none'
            WHEN t.covers      THEN 'in_term'
            ELSE 'wind_down' END                                      AS attribution
  FROM parliament.mp_expenses e
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
       count(*) FILTER (WHERE party_changed_in_quarter)             AS split_quarters,
       round(sum(total_cad) FILTER (WHERE attribution = 'wind_down'), 2) AS total_cad_wind_down
  FROM parliament.v_mp_expenses_by_party
 GROUP BY 1, 2;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT ON parliament.v_mp_expenses_by_party, parliament.v_party_mp_costs_by_year TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('096', '096_mp_expenses_wind_down.sql', 'MP expenses after leaving office attributed to the last party sat for', now())
ON CONFLICT (version) DO NOTHING;
