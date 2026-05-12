-- database/migrations/374_civic_transparency_schema.sql
-- Phase 1 of Civic Transparency: GEDS directory ingestion.
-- Spec: docs/superpowers/specs/2026-05-04-civic-transparency-phase1-geds.md

CREATE SCHEMA IF NOT EXISTS civic_transparency;

CREATE TABLE IF NOT EXISTS civic_transparency.org_units (
    id              SERIAL PRIMARY KEY,
    parent_id       INTEGER REFERENCES civic_transparency.org_units(id),
    dn              TEXT NOT NULL UNIQUE,
    dn_b64          TEXT NOT NULL,
    level           SMALLINT NOT NULL,
    name_en         TEXT NOT NULL,
    name_fr         TEXT,
    abbreviation_en TEXT,
    abbreviation_fr TEXT,
    coverage        TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (coverage IN ('full','partial','none','opted_out','unknown')),
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_org_units_parent  ON civic_transparency.org_units(parent_id);
CREATE INDEX IF NOT EXISTS idx_org_units_abbr_en ON civic_transparency.org_units(abbreviation_en);

CREATE TABLE IF NOT EXISTS civic_transparency.federal_employees (
    id               SERIAL PRIMARY KEY,
    source_dn        TEXT NOT NULL UNIQUE,
    org_unit_id      INTEGER NOT NULL REFERENCES civic_transparency.org_units(id),
    surname          TEXT NOT NULL,
    given_name       TEXT,
    title_en         TEXT,
    title_fr         TEXT,
    classification   TEXT,
    role_tag         TEXT CHECK (role_tag IS NULL OR role_tag IN
                       ('minister','deputy_minister','senator','mp')),
    phone            TEXT,
    email            TEXT,
    location_en      TEXT,
    manager_dn       TEXT,
    manager_id       INTEGER REFERENCES civic_transparency.federal_employees(id),
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT now(),
    departed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_fed_emp_org            ON civic_transparency.federal_employees(org_unit_id);
CREATE INDEX IF NOT EXISTS idx_fed_emp_role           ON civic_transparency.federal_employees(role_tag) WHERE role_tag IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fed_emp_classification ON civic_transparency.federal_employees(classification);
CREATE INDEX IF NOT EXISTS idx_fed_emp_active         ON civic_transparency.federal_employees(departed_at) WHERE departed_at IS NULL;

CREATE TABLE IF NOT EXISTS civic_transparency.geds_snapshots (
    id                  SERIAL PRIMARY KEY,
    run_started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_finished_at     TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','partial','failed')),
    org_units_seen      INTEGER NOT NULL DEFAULT 0,
    employees_seen      INTEGER NOT NULL DEFAULT 0,
    employees_new       INTEGER NOT NULL DEFAULT 0,
    employees_departed  INTEGER NOT NULL DEFAULT 0,
    employees_changed   INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT
);

CREATE TABLE IF NOT EXISTS civic_transparency.geds_movements (
    id              SERIAL PRIMARY KEY,
    snapshot_id     INTEGER NOT NULL REFERENCES civic_transparency.geds_snapshots(id),
    employee_id     INTEGER REFERENCES civic_transparency.federal_employees(id),
    movement_type   TEXT NOT NULL CHECK (movement_type IN
                       ('new','departed','title_changed','org_changed','classification_changed')),
    before_value    JSONB,
    after_value     JSONB,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_geds_movements_snapshot ON civic_transparency.geds_movements(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_geds_movements_emp      ON civic_transparency.geds_movements(employee_id);

CREATE TABLE IF NOT EXISTS civic_transparency.geds_raw_pages (
    id           BIGSERIAL PRIMARY KEY,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    url          TEXT NOT NULL,
    status_code  SMALLINT NOT NULL,
    body         BYTEA,
    purge_after  TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 days')
);
CREATE INDEX IF NOT EXISTS idx_geds_raw_purge ON civic_transparency.geds_raw_pages(purge_after);
