-- Industry Framework plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Industry configuration (one row per tenant)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS industry_config (
    id               SERIAL PRIMARY KEY,
    industry_type    VARCHAR(50) NOT NULL
                         CHECK (industry_type IN (
                             'construction', 'electrical', 'plumbing',
                             'mechanical', 'hvac', 'general', 'ai_agency', 'other'
                         )),
    company_license  VARCHAR(255),
    license_expiry   DATE,
    insurance_info   JSONB DEFAULT '{}',
    certifications   JSONB DEFAULT '[]',
    service_area     TEXT,
    settings         JSONB DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Jobs (core of all trades)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id               SERIAL PRIMARY KEY,
    job_number       VARCHAR(50) UNIQUE,
    customer_id      INTEGER,
    title            VARCHAR(255) NOT NULL,
    description      TEXT,
    job_type         VARCHAR(50) DEFAULT 'service'
                         CHECK (job_type IN (
                             'service', 'project', 'maintenance',
                             'emergency', 'inspection', 'consultation'
                         )),
    status           VARCHAR(20) DEFAULT 'quoted'
                         CHECK (status IN (
                             'quoted', 'approved', 'in_progress', 'on_hold',
                             'completed', 'cancelled', 'invoiced'
                         )),
    priority         VARCHAR(20) DEFAULT 'normal'
                         CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    estimated_cost   DECIMAL(12, 2),
    actual_cost      DECIMAL(12, 2),
    estimated_hours  DECIMAL(8, 2),
    actual_hours     DECIMAL(8, 2),
    start_date       DATE,
    end_date         DATE,
    completion_date  DATE,
    site_address     TEXT,
    site_notes       TEXT,
    assigned_to      VARCHAR(255),
    tags             JSONB DEFAULT '[]',
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Job line items (materials, labour, equipment, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_items (
    id           SERIAL PRIMARY KEY,
    job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    item_type    VARCHAR(20) NOT NULL
                     CHECK (item_type IN (
                         'labor', 'material', 'equipment',
                         'subcontractor', 'permit', 'other'
                     )),
    description  VARCHAR(255) NOT NULL,
    quantity     DECIMAL(10, 2) DEFAULT 1,
    unit_price   DECIMAL(10, 2) NOT NULL,
    total        DECIMAL(10, 2) NOT NULL,
    notes        TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Job notes / site diary
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_notes (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    author      VARCHAR(255) NOT NULL,
    content     TEXT NOT NULL,
    note_type   VARCHAR(20) DEFAULT 'general'
                    CHECK (note_type IN (
                        'general', 'safety', 'inspection',
                        'change_order', 'site_condition'
                    )),
    attachments JSONB DEFAULT '[]',
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Government / public-sector tender opportunities
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS government_opportunities (
    id               SERIAL PRIMARY KEY,
    title            VARCHAR(500) NOT NULL,
    source           VARCHAR(100) NOT NULL,
    reference_number VARCHAR(100),
    description      TEXT,
    industry_types   JSONB DEFAULT '[]',
    region           VARCHAR(100),
    value_min        DECIMAL(12, 2),
    value_max        DECIMAL(12, 2),
    deadline         DATE,
    url              TEXT,
    status           VARCHAR(20) DEFAULT 'new'
                         CHECK (status IN (
                             'new', 'reviewing', 'applied',
                             'awarded', 'expired', 'not_relevant'
                         )),
    match_score      INTEGER DEFAULT 0,
    notes            TEXT,
    metadata         JSONB DEFAULT '{}',
    discovered_at    TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Permits & licences tied to jobs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permits_licenses (
    id                 SERIAL PRIMARY KEY,
    job_id             INTEGER REFERENCES jobs(id),
    permit_type        VARCHAR(100) NOT NULL,
    permit_number      VARCHAR(100),
    issuing_authority  VARCHAR(255),
    status             VARCHAR(20) DEFAULT 'pending'
                           CHECK (status IN (
                               'pending', 'submitted', 'approved', 'denied', 'expired'
                           )),
    applied_date       DATE,
    approval_date      DATE,
    expiry_date        DATE,
    cost               DECIMAL(10, 2),
    notes              TEXT,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_jobs_customer_id   ON jobs (customer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status         ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_job_type       ON jobs (job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_start_date     ON jobs (start_date);
CREATE INDEX IF NOT EXISTS idx_job_items_job_id    ON job_items (job_id);
CREATE INDEX IF NOT EXISTS idx_job_notes_job_id    ON job_notes (job_id);
CREATE INDEX IF NOT EXISTS idx_opps_status         ON government_opportunities (status);
CREATE INDEX IF NOT EXISTS idx_opps_deadline       ON government_opportunities (deadline);
CREATE INDEX IF NOT EXISTS idx_permits_job_id      ON permits_licenses (job_id);
CREATE INDEX IF NOT EXISTS idx_permits_status      ON permits_licenses (status);
CREATE INDEX IF NOT EXISTS idx_permits_expiry      ON permits_licenses (expiry_date);
