-- Plumbing industry plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Service calls
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plumbing_service_calls (
    id              SERIAL PRIMARY KEY,
    job_id          INT,
    customer_id     INT,
    call_type       VARCHAR(50) NOT NULL
                        CHECK (call_type IN (
                            'emergency', 'repair', 'installation',
                            'maintenance', 'inspection', 'drain', 'backflow'
                        )),
    priority        VARCHAR(20) DEFAULT 'normal'
                        CHECK (priority IN ('low', 'normal', 'high', 'emergency')),
    description     TEXT,
    technician      VARCHAR(255),
    scheduled_date  TIMESTAMP,
    completed_date  TIMESTAMP,
    status          VARCHAR(20) DEFAULT 'new'
                        CHECK (status IN (
                            'new', 'dispatched', 'en_route', 'on_site',
                            'completed', 'cancelled'
                        )),
    diagnosis       TEXT,
    resolution      TEXT,
    parts_used      JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Fixtures
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plumbing_fixtures (
    id              SERIAL PRIMARY KEY,
    job_id          INT,
    fixture_type    VARCHAR(50) NOT NULL
                        CHECK (fixture_type IN (
                            'toilet', 'sink', 'faucet', 'shower', 'bathtub',
                            'water_heater', 'disposal', 'dishwasher', 'washer', 'other'
                        )),
    brand           VARCHAR(100),
    model           VARCHAR(100),
    location        VARCHAR(255),
    install_date    DATE,
    warranty_expiry DATE,
    status          VARCHAR(20) DEFAULT 'active'
                        CHECK (status IN ('active', 'needs_repair', 'replaced', 'removed')),
    serial_number   VARCHAR(100),
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Parts inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plumbing_parts_inventory (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    category     VARCHAR(50)
                     CHECK (category IN (
                         'pipe', 'fitting', 'valve', 'fixture',
                         'tool', 'sealant', 'other'
                     )),
    sku          VARCHAR(100),
    quantity     INT DEFAULT 0,
    min_quantity INT DEFAULT 5,
    unit_cost    DECIMAL(10, 2),
    supplier     VARCHAR(255),
    location     VARCHAR(100),
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Backflow tests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plumbing_backflow_tests (
    id                   SERIAL PRIMARY KEY,
    job_id               INT,
    device_location      VARCHAR(255) NOT NULL,
    device_type          VARCHAR(100),
    serial_number        VARCHAR(100),
    test_date            DATE NOT NULL,
    tester_name          VARCHAR(255),
    test_result          VARCHAR(20) DEFAULT 'pending'
                             CHECK (test_result IN ('pending', 'pass', 'fail')),
    pressure_readings    JSONB DEFAULT '{}',
    next_test_date       DATE,
    certification_number VARCHAR(100),
    notes                TEXT,
    created_at           TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_plumbing_sc_status      ON plumbing_service_calls (status);
CREATE INDEX IF NOT EXISTS idx_plumbing_sc_call_type   ON plumbing_service_calls (call_type);
CREATE INDEX IF NOT EXISTS idx_plumbing_sc_job_id      ON plumbing_service_calls (job_id);
CREATE INDEX IF NOT EXISTS idx_plumbing_sc_customer_id ON plumbing_service_calls (customer_id);
CREATE INDEX IF NOT EXISTS idx_plumbing_fixtures_job   ON plumbing_fixtures (job_id);
CREATE INDEX IF NOT EXISTS idx_plumbing_fixtures_type  ON plumbing_fixtures (fixture_type);
CREATE INDEX IF NOT EXISTS idx_plumbing_inv_category   ON plumbing_parts_inventory (category);
CREATE INDEX IF NOT EXISTS idx_plumbing_backflow_date  ON plumbing_backflow_tests (test_date);
CREATE INDEX IF NOT EXISTS idx_plumbing_backflow_next  ON plumbing_backflow_tests (next_test_date);
CREATE INDEX IF NOT EXISTS idx_plumbing_backflow_job   ON plumbing_backflow_tests (job_id);
