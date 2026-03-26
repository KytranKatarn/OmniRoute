-- CRM plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

CREATE TABLE IF NOT EXISTS crm_customers (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255),
    phone       VARCHAR(50),
    company     VARCHAR(255),
    status      VARCHAR(20) DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive', 'lead', 'prospect')),
    source      VARCHAR(50),
    notes       TEXT,
    tags        JSONB DEFAULT '[]',
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_segments (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    rules       JSONB DEFAULT '{}',
    is_dynamic  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_segment_members (
    id          SERIAL PRIMARY KEY,
    segment_id  INTEGER NOT NULL REFERENCES crm_segments(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES crm_customers(id) ON DELETE CASCADE,
    added_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE (segment_id, customer_id)
);

CREATE TABLE IF NOT EXISTS crm_interactions (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES crm_customers(id) ON DELETE CASCADE,
    type        VARCHAR(50) NOT NULL
                    CHECK (type IN ('email', 'call', 'meeting', 'note', 'order', 'invoice', 'support', 'other')),
    subject     VARCHAR(255),
    content     TEXT,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_imports (
    id             SERIAL PRIMARY KEY,
    filename       VARCHAR(255),
    total_rows     INTEGER DEFAULT 0,
    imported_rows  INTEGER DEFAULT 0,
    failed_rows    INTEGER DEFAULT 0,
    status         VARCHAR(20) DEFAULT 'pending'
                       CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    errors         JSONB DEFAULT '[]',
    created_at     TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_crm_customers_email  ON crm_customers (email);
CREATE INDEX IF NOT EXISTS idx_crm_customers_status ON crm_customers (status);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_customer ON crm_interactions (customer_id);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_type    ON crm_interactions (type);
