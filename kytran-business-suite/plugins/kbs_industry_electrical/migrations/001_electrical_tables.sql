-- Electrical industry vertical plugin tables — run inside tenant schema.
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Electrical panels
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS electrical_panels (
    id           SERIAL PRIMARY KEY,
    job_id       INTEGER,
    name         VARCHAR(255) NOT NULL,
    panel_type   VARCHAR(50) DEFAULT 'main'
                     CHECK (panel_type IN ('main', 'sub', 'distribution', 'emergency')),
    amperage     INTEGER NOT NULL,
    voltage      INTEGER DEFAULT 120,
    phases       INTEGER DEFAULT 1
                     CHECK (phases IN (1, 3)),
    spaces       INTEGER,
    spaces_used  INTEGER DEFAULT 0,
    location     VARCHAR(255),
    notes        TEXT,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Electrical circuits (belong to a panel)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS electrical_circuits (
    id             SERIAL PRIMARY KEY,
    panel_id       INTEGER NOT NULL REFERENCES electrical_panels(id) ON DELETE CASCADE,
    circuit_number INTEGER NOT NULL,
    description    VARCHAR(255) NOT NULL,
    amperage       INTEGER NOT NULL,
    wire_size      VARCHAR(20),
    breaker_type   VARCHAR(50) DEFAULT 'standard'
                       CHECK (breaker_type IN ('standard', 'gfci', 'afci', 'dual_function')),
    load_watts     INTEGER DEFAULT 0,
    is_dedicated   BOOLEAN DEFAULT FALSE,
    notes          TEXT,
    created_at     TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Load calculations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS electrical_load_calculations (
    id                      SERIAL PRIMARY KEY,
    job_id                  INTEGER,
    building_type           VARCHAR(50),
    total_sqft              INTEGER,
    general_lighting_load   DECIMAL(10,2),
    small_appliance_load    DECIMAL(10,2),
    fixed_appliance_load    DECIMAL(10,2),
    hvac_load               DECIMAL(10,2),
    total_calculated_load   DECIMAL(10,2),
    required_service_amps   INTEGER,
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Materials
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS electrical_materials (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER,
    name        VARCHAR(255) NOT NULL,
    category    VARCHAR(50)
                    CHECK (category IN ('wire', 'conduit', 'panel', 'breaker', 'device', 'fixture', 'other')),
    quantity    DECIMAL(10,2) DEFAULT 1,
    unit        VARCHAR(20) DEFAULT 'each',
    unit_cost   DECIMAL(10,2),
    total_cost  DECIMAL(10,2),
    supplier    VARCHAR(255),
    status      VARCHAR(20) DEFAULT 'needed'
                    CHECK (status IN ('needed', 'ordered', 'received', 'installed')),
    created_at  TIMESTAMP DEFAULT NOW()
);
