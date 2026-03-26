-- Mechanical / HVAC plugin tables
-- Runs inside the tenant schema (search_path already set by run_migration_file)

CREATE TABLE IF NOT EXISTS hvac_systems (
    id               SERIAL PRIMARY KEY,
    job_id           INTEGER,
    system_type      TEXT NOT NULL CHECK (system_type IN (
                         'heating', 'cooling', 'ventilation',
                         'heat_pump', 'boiler', 'chiller', 'other'
                     )),
    manufacturer     TEXT,
    model            TEXT,
    serial_number    TEXT,
    install_date     DATE,
    warranty_expiry  DATE,
    capacity_btu     INTEGER,
    efficiency_rating DECIMAL(6, 2),
    location         TEXT,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
                         'active', 'needs_service', 'decommissioned'
                     )),
    notes            TEXT,
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS maintenance_schedules (
    id             SERIAL PRIMARY KEY,
    system_id      INTEGER NOT NULL REFERENCES hvac_systems (id) ON DELETE CASCADE,
    task_name      TEXT NOT NULL,
    frequency      TEXT NOT NULL CHECK (frequency IN (
                       'monthly', 'quarterly', 'semi_annual', 'annual'
                   )),
    last_performed DATE,
    next_due       DATE,
    technician     TEXT,
    notes          TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS energy_audits (
    id                 SERIAL PRIMARY KEY,
    job_id             INTEGER,
    building_sqft      INTEGER,
    current_system     TEXT,
    recommended_system TEXT,
    estimated_savings  DECIMAL(12, 2),
    payback_years      DECIMAL(5, 2),
    audit_date         DATE,
    auditor            TEXT,
    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
                           'draft', 'submitted', 'approved'
                       )),
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS commissioning_reports (
    id           SERIAL PRIMARY KEY,
    system_id    INTEGER NOT NULL REFERENCES hvac_systems (id) ON DELETE CASCADE,
    report_type  TEXT NOT NULL CHECK (report_type IN (
                     'startup', 'balance', 'performance', 'seasonal'
                 )),
    test_results JSONB NOT NULL DEFAULT '{}',
    passed       BOOLEAN,
    technician   TEXT,
    report_date  DATE,
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_hvac_systems_status     ON hvac_systems (status);
CREATE INDEX IF NOT EXISTS idx_hvac_systems_job_id     ON hvac_systems (job_id);
CREATE INDEX IF NOT EXISTS idx_maint_schedules_next    ON maintenance_schedules (next_due) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_maint_schedules_system  ON maintenance_schedules (system_id);
CREATE INDEX IF NOT EXISTS idx_energy_audits_status    ON energy_audits (status);
CREATE INDEX IF NOT EXISTS idx_comm_reports_system     ON commissioning_reports (system_id);
