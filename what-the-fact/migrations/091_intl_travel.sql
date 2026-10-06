-- 091_intl_travel.sql — senators' international travel from the THREE places the Senate/Parliament disclose it.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY: a senator's own Travel table (parliament.senate_travel_trips, migration 090) is only ONE of three
-- disclosure systems, and the other two carry foreign travel the first never shows:
--   1. Senators' own Travel expense detail      -> parliament.senate_travel_trips   (already ingested)
--   2. Senate COMMITTEE travel reports (PDF)    -> intl_travel_events source='committee'
--      sencanada.ca/ProActiveDisclosure/Committees/en/<Y>/<Q>/<COMM>-Travel-<place>-E.pdf
--      e.g. Foreign Affairs to Berlin / Oslo / London. Group-level: ONE total per trip (participants include
--      staff and interpreters), so these rows carry no per-senator amount.
--   3. International & Interparliamentary Affairs (IIA) delegation reports (PDF)
--      parl.ca/DocumentViewer/en/IIA/financial-report/<id> — parliamentary associations (NATO PA, IPU, CPA,
--      APF, ParlAmericas ...). Delegation total PLUS an individual line per parliamentarian, so
--      intl_travel_senators holds one row per SENATOR on each delegation.
-- Measured 2026-10-06 over 2023-01-16..2026-03-17: system 1 alone gives $688,844 confirmed international;
-- committees add $260,944; IIA senator lines add ~$1.14M that are NOT in system 1. A published figure has to
-- say which of the three it includes.
--
-- DOUBLE COUNTING IS THE HAZARD. The same trip can be in system 1 AND in an IIA report (Housakos' Paris trip,
-- Apr 2023). Every IIA senator line therefore records overlap: 'in_expense_travel' (a leg of that senator
-- falls within the delegation's dates — already counted in system 1, DO NOT add), 'not_in_expense_travel'
-- (additive), or 'unmatched_senator' (name did not resolve to the roster, or the delegation has no start date; shown as its own
--   component, never part of the confirmed figure).
-- The match is by senator_id + date window, not a surname substring.
--
-- is_foreign is three-valued like senate_travel_trips.is_international: NULL = could not tell.
--
-- Rows for one (source, source_ref) are REPLACED as a set by the ingest (reports are amended).
-- Re-runnable: IF NOT EXISTS + CREATE OR REPLACE VIEW + ON CONFLICT DO NOTHING.

CREATE TABLE IF NOT EXISTS parliament.intl_travel_events (
    id                   bigserial     PRIMARY KEY,
    source               text          NOT NULL CHECK (source IN ('committee', 'iia')),
    source_ref           text          NOT NULL,        -- committee: PDF path; iia: DocumentViewer report id
    body                 text,                          -- committee code (AEFA, SECD ...) / association acronym (CANA, UIPU ...)
    title                text,
    destination          text,
    event_start          date,                          -- NULL when the report gives only an ambiguous d/m date
    event_end            date,
    report_period        text,                          -- committee: Senate calendar quarter "<Y>-Q<q>" it was published under
    is_foreign           boolean,
    delegation_total_cad numeric(12,2),                 -- whole delegation / group, INCLUDING MPs, staff, interpreters
    senator_total_cad    numeric(12,2),                 -- sum of the senator lines (iia only; NULL for committee)
    n_senators           integer,
    cancelled            boolean       NOT NULL DEFAULT false,   -- the report says the trip was cancelled (costs are fees)
    source_url           text          NOT NULL,
    synced_at            timestamptz   NOT NULL DEFAULT now(),
    UNIQUE (source, source_ref)
);
CREATE INDEX IF NOT EXISTS intl_travel_events_start_idx ON parliament.intl_travel_events (event_start);

CREATE TABLE IF NOT EXISTS parliament.intl_travel_senators (
    id                bigserial     PRIMARY KEY,
    event_id          bigint        NOT NULL REFERENCES parliament.intl_travel_events(id) ON DELETE CASCADE,
    senator_id        integer       REFERENCES parliament.senators(id) ON DELETE SET NULL,
    name_as_published text          NOT NULL,
    amount_cad        numeric(12,2) NOT NULL,
    overlap           text          NOT NULL CHECK (overlap IN ('in_expense_travel', 'not_in_expense_travel', 'unmatched_senator')),
    overlap_leg_ids   bigint[],                         -- senate_travel_trips.id the date-window match found
    overlap_cad       numeric(12,2)                     -- what system 1 already holds for those legs
);
CREATE INDEX IF NOT EXISTS intl_travel_senators_event_idx ON parliament.intl_travel_senators (event_id);

-- By calendar year, one row per component, so a caller can state exactly what a figure includes.
-- 'senator_expenses' + 'committee' + 'iia_senators_not_in_expenses' are ADDITIVE; 'iia_senators_in_expenses' is
-- already inside 'senator_expenses' and is shown only so the overlap is visible. Two components are UPPER-BOUND
-- add-ons, never part of the confirmed figure: 'senator_expenses_unclassified' (destination we could not classify)
-- and 'iia_senators_unmatched' (an IIA senator line we could not tie to the roster or to a delegation date, so
-- its overlap with system 1 is unknown).
-- Exact windows (e.g. 2023-01-16..2026-03-17): query the tables, a year is too coarse.
CREATE OR REPLACE VIEW parliament.v_senate_intl_travel_by_year AS
SELECT yr, component, n, round(amount_cad, 2) AS amount_cad FROM (
    SELECT extract(year FROM trip_start)::int AS yr, 'senator_expenses'::text AS component,
           count(*) AS n, sum(total_cad) AS amount_cad
      FROM parliament.senate_travel_trips WHERE is_international GROUP BY 1
    UNION ALL
    SELECT extract(year FROM trip_start)::int, 'senator_expenses_unclassified', count(*), sum(total_cad)
      FROM parliament.senate_travel_trips WHERE is_international IS NULL GROUP BY 1
    UNION ALL
    SELECT extract(year FROM COALESCE(event_start,
               make_date(split_part(report_period, '-Q', 1)::int, (split_part(report_period, '-Q', 2)::int - 1) * 3 + 1, 1)))::int,
           'committee', count(*), sum(delegation_total_cad)
      FROM parliament.intl_travel_events WHERE source = 'committee' AND is_foreign GROUP BY 1
    UNION ALL
    SELECT extract(year FROM e.event_start)::int, 'iia_senators_not_in_expenses', count(*), sum(s.amount_cad)
      FROM parliament.intl_travel_senators s JOIN parliament.intl_travel_events e ON e.id = s.event_id
     WHERE e.source = 'iia' AND e.is_foreign AND s.overlap = 'not_in_expense_travel' GROUP BY 1
    UNION ALL
    SELECT extract(year FROM e.event_start)::int, 'iia_senators_unmatched', count(*), sum(s.amount_cad)
      FROM parliament.intl_travel_senators s JOIN parliament.intl_travel_events e ON e.id = s.event_id
     WHERE e.source = 'iia' AND e.is_foreign AND s.overlap = 'unmatched_senator' GROUP BY 1
    UNION ALL
    SELECT extract(year FROM e.event_start)::int, 'iia_senators_in_expenses', count(*), sum(s.amount_cad)
      FROM parliament.intl_travel_senators s JOIN parliament.intl_travel_events e ON e.id = s.event_id
     WHERE e.source = 'iia' AND e.is_foreign AND s.overlap = 'in_expense_travel' GROUP BY 1
) x ORDER BY yr, component;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.intl_travel_events, parliament.intl_travel_senators TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.intl_travel_events_id_seq, parliament.intl_travel_senators_id_seq TO wtfuser;
        GRANT SELECT ON parliament.v_senate_intl_travel_by_year TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('091', '091_intl_travel.sql',
        'Senators international travel from committee + IIA reports, with overlap against the senators own Travel table', now())
ON CONFLICT (version) DO NOTHING;
