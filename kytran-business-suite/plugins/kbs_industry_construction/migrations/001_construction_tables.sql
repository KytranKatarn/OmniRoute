-- Construction industry plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Construction projects (extends base jobs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS construction_projects (
    id                    SERIAL PRIMARY KEY,
    job_id                INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    project_type          VARCHAR(50) DEFAULT 'commercial'
                              CHECK (project_type IN (
                                  'residential', 'commercial', 'industrial',
                                  'infrastructure', 'renovation'
                              )),
    general_contractor    VARCHAR(255),
    site_supervisor       VARCHAR(255),
    project_value         DECIMAL(12, 2),
    completion_percentage INTEGER DEFAULT 0
                              CHECK (completion_percentage BETWEEN 0 AND 100),
    phases                JSONB DEFAULT '[]',
    safety_plan           TEXT,
    weather_delays        INTEGER DEFAULT 0,
    metadata              JSONB DEFAULT '{}',
    created_at            TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Subcontractors
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS construction_subcontractors (
    id               SERIAL PRIMARY KEY,
    company_name     VARCHAR(255) NOT NULL,
    contact_name     VARCHAR(255),
    phone            VARCHAR(50),
    email            VARCHAR(255),
    trade            VARCHAR(100) NOT NULL,
    license_number   VARCHAR(100),
    insurance_expiry DATE,
    hourly_rate      DECIMAL(8, 2),
    rating           INTEGER CHECK (rating BETWEEN 1 AND 5),
    is_active        BOOLEAN DEFAULT TRUE,
    notes            TEXT,
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- RFIs (Requests for Information)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS construction_rfis (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES construction_projects(id) ON DELETE CASCADE,
    rfi_number   VARCHAR(20) UNIQUE,
    subject      VARCHAR(255) NOT NULL,
    description  TEXT,
    status       VARCHAR(20) DEFAULT 'open'
                     CHECK (status IN ('open', 'responded', 'closed')),
    submitted_by VARCHAR(255),
    response     TEXT,
    responded_at TIMESTAMP,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Change Orders
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS construction_change_orders (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES construction_projects(id) ON DELETE CASCADE,
    co_number   VARCHAR(20) UNIQUE,
    description TEXT NOT NULL,
    reason      VARCHAR(100),
    amount      DECIMAL(12, 2) NOT NULL,
    status      VARCHAR(20) DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
    approved_by VARCHAR(255),
    approved_at TIMESTAMP,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Inspections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS construction_inspections (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES construction_projects(id) ON DELETE CASCADE,
    inspection_type VARCHAR(100) NOT NULL,
    inspector       VARCHAR(255),
    scheduled_date  DATE,
    status          VARCHAR(20) DEFAULT 'scheduled'
                        CHECK (status IN ('scheduled', 'passed', 'failed', 'rescheduled')),
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_construction_projects_job_id   ON construction_projects (job_id);
CREATE INDEX IF NOT EXISTS idx_construction_rfis_project_id   ON construction_rfis (project_id);
CREATE INDEX IF NOT EXISTS idx_construction_rfis_status       ON construction_rfis (status);
CREATE INDEX IF NOT EXISTS idx_construction_cos_project_id    ON construction_change_orders (project_id);
CREATE INDEX IF NOT EXISTS idx_construction_cos_status        ON construction_change_orders (status);
CREATE INDEX IF NOT EXISTS idx_construction_insp_project_id   ON construction_inspections (project_id);
CREATE INDEX IF NOT EXISTS idx_construction_insp_status       ON construction_inspections (status);
CREATE INDEX IF NOT EXISTS idx_construction_subs_trade        ON construction_subcontractors (trade);
CREATE INDEX IF NOT EXISTS idx_construction_subs_active       ON construction_subcontractors (is_active);
