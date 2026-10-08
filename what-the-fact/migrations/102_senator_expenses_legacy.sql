-- 102: parliament.senator_expenses_legacy — senators' quarterly expenditure reports, Sept 2010 - June 2016.
--
-- The Senate's pre-2016-Q3 disclosure (one PDF per senator per period; see ingest/parliament/senate_legacy.py). Its periods are
-- Mar-May / Jun-Aug / Sep-Nov / Dec-Feb (the last, 2016-03-01..2016-06-30, is four months), NOT calendar quarters, so they are
-- stored with explicit period_start/period_end and never forced into senator_expenses' 'YYYY-Qn' periods.
--
-- The report prints NO total and omits nothing: five amounts per row, stored one column each (a figure can be negative — a
-- repayment). total_cad / travel_cad are sums computed by the loader. senator_id is NULLABLE: a senator who is not in
-- parliament.senators (former senators are not all on the roster) is kept by published name rather than getting a stub roster row
-- that other pages would then list. Least privilege like senator_expenses: the ingest may INSERT/UPDATE/SELECT, never DELETE.
-- Re-runnable.

CREATE TABLE IF NOT EXISTS parliament.senator_expenses_legacy (
    id                 BIGSERIAL     PRIMARY KEY,
    senator_id         INTEGER       REFERENCES parliament.senators(id) ON DELETE SET NULL,
    name_as_published  TEXT          NOT NULL,
    period_start       DATE          NOT NULL,
    period_end         DATE          NOT NULL,
    office_cad         NUMERIC(14,2) NOT NULL,      -- Staff & Office (1)
    hospitality_cad    NUMERIC(14,2) NOT NULL,
    living_cad         NUMERIC(14,2) NOT NULL,      -- Living expenses, National Capital Region
    travel_regular_cad NUMERIC(14,2) NOT NULL,      -- Travel 2a: province/territory <-> Ottawa
    travel_other_cad   NUMERIC(14,2) NOT NULL,      -- Travel 2b: all other
    travel_cad         NUMERIC(14,2) NOT NULL,      -- 2a + 2b
    total_cad          NUMERIC(14,2) NOT NULL,      -- office + hospitality + living + travel
    source_code        TEXT          NOT NULL,      -- the file code, e.g. AndreA
    source_url         TEXT          NOT NULL,
    synced_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (period_end, source_code)
);
CREATE INDEX IF NOT EXISTS senator_expenses_legacy_senator_idx ON parliament.senator_expenses_legacy (senator_id);
CREATE INDEX IF NOT EXISTS senator_expenses_legacy_period_idx  ON parliament.senator_expenses_legacy (period_end);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        REVOKE DELETE, TRUNCATE ON parliament.senator_expenses_legacy FROM wtfuser;
        GRANT SELECT, INSERT, UPDATE ON parliament.senator_expenses_legacy TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.senator_expenses_legacy_id_seq TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('102', '102_senator_expenses_legacy.sql', 'Senators quarterly expenditure reports Sept 2010 - June 2016 (own periods, five amounts per senator-period)', now())
ON CONFLICT (version) DO NOTHING;
