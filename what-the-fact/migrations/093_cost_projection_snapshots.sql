-- 093_cost_projection_snapshots.sql — a ledger of what /cost projected, so the page can show how far off it was.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY: the year is not over when it is almost over — expense disclosures lag by a quarter or more, so in October
-- only the first two quarters of 2026 are public. /cost projects the full year from the quarters on file, and that
-- projection is revised as each quarter is released. To say "we projected $X after two quarters, $Y after three,
-- and the year came in at $Z", every projection has to be KEPT. One row per (year, set of disclosed quarters),
-- written once by the weekly cost_projection job the first time that quarter set is seen — a later run with the
-- same quarters changes nothing (ON CONFLICT DO NOTHING), so a row records what was published at that stage.
--
-- quarters_key is the sorted, comma-joined quarter labels on file ("Q1,Q4" = Apr-Jun + Jan-Mar of the label year).
-- parliamentary_cad = MP + senator (the page headline basis); combined_cad adds ministerial travel/hospitality.
-- low/high are the range from the lowest and highest prior-year seasonal share (see cost.seasonal_projection).
--
-- Re-runnable: IF NOT EXISTS + ON CONFLICT DO NOTHING.

CREATE TABLE IF NOT EXISTS parliament.cost_projection_snapshots (
    year              integer       NOT NULL,
    quarters_key      text          NOT NULL,
    as_of             timestamptz   NOT NULL DEFAULT now(),
    parliamentary_cad numeric(14,0) NOT NULL,
    combined_cad      numeric(14,0) NOT NULL,
    low_cad           numeric(14,0),
    high_cad          numeric(14,0),
    method            text,
    PRIMARY KEY (year, quarters_key)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.cost_projection_snapshots TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('093', '093_cost_projection_snapshots.sql',
        'Ledger of /cost full-year projections per disclosed-quarter set, for projected-vs-actual comparison', now())
ON CONFLICT (version) DO NOTHING;
