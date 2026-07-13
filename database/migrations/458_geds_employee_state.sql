-- Migration 458: GEDS employee last-known-value cache for movement detection.
--
-- Stores the prior (org_unit_id, role_tag) for each active federal employee so
-- the daily GEDS refresh can diff the CURRENT roster against the PRIOR run and
-- emit 'org_changed' / 'role_changed' rows into civic_transparency.geds_movements.
--
-- On the first run after deploy the table is empty, so no changes are detected —
-- the run simply populates it. Idempotent.

CREATE TABLE IF NOT EXISTS civic_transparency.geds_employee_state (
    employee_id BIGINT PRIMARY KEY
        REFERENCES civic_transparency.federal_employees(id) ON DELETE CASCADE,
    org_unit_id BIGINT,
    role_tag TEXT,
    updated_snapshot_id BIGINT
);

-- Widen the geds_movements.movement_type allowlist to admit 'role_changed'.
-- The existing CHECK permits new/departed/title_changed/org_changed/
-- classification_changed but NOT role_changed, so the new detector's INSERT
-- would abort the whole detect_movements() transaction without this. The new
-- allowlist is a strict superset, so all existing rows remain valid.
-- Idempotent: DROP IF EXISTS then re-ADD with a fixed name.
ALTER TABLE civic_transparency.geds_movements
    DROP CONSTRAINT IF EXISTS geds_movements_movement_type_check;
ALTER TABLE civic_transparency.geds_movements
    ADD CONSTRAINT geds_movements_movement_type_check
    CHECK (movement_type = ANY (ARRAY[
        'new', 'departed', 'title_changed',
        'org_changed', 'role_changed', 'classification_changed'
    ]));
