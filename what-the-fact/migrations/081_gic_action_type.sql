-- 081_gic_action_type.sql
-- GIC vacancy tracking (Dev HQ #6621 item 2): distinguish appointment-type OICs
-- from termination/revocation/resignation-type OICs so "currently vacant" can
-- be derived as the latest action per position being a termination with no
-- later (re)appointment. Existing rows are all appointment-type (the ingest
-- only ever captured those until now) — backfill is exact, not a guess.

ALTER TABLE gov_watch.gic_appointments
    ADD COLUMN IF NOT EXISTS action_type TEXT NOT NULL DEFAULT 'appointment';

CREATE INDEX IF NOT EXISTS idx_gic_action_type
    ON gov_watch.gic_appointments(action_type);

-- Position identity for the vacancy derivation: department + organization is
-- the closest already-extracted proxy for "which post" without a real
-- position-id from the source (the OIC site has none). Index supports the
-- "latest action per position" window query in routes.py.
CREATE INDEX IF NOT EXISTS idx_gic_dept_org_date
    ON gov_watch.gic_appointments(department, organization, oic_date DESC);
