-- Contracts & Legal plugin tables (tenant schema)

CREATE TABLE IF NOT EXISTS contract_templates (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    content     TEXT DEFAULT '',
    doc_type    VARCHAR(50) DEFAULT 'contract'
                    CHECK (doc_type IN ('contract','nda','agreement','proposal','terms','other')),
    variables   JSONB DEFAULT '[]',
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contracts (
    id                    SERIAL PRIMARY KEY,
    contract_number       VARCHAR(50) UNIQUE,
    template_id           INT REFERENCES contract_templates(id),
    customer_id           INT,
    title                 VARCHAR(255) NOT NULL,
    content               TEXT DEFAULT '',
    status                VARCHAR(20) DEFAULT 'draft'
                              CHECK (status IN ('draft','sent','viewed','signed','expired','cancelled','renewed')),
    value                 DECIMAL(10,2),
    start_date            DATE,
    end_date              DATE,
    signed_at             TIMESTAMP,
    signed_by             VARCHAR(255),
    renewal_type          VARCHAR(20) DEFAULT 'manual'
                              CHECK (renewal_type IN ('manual','auto','none')),
    renewal_reminder_days INT DEFAULT 30,
    tags                  JSONB DEFAULT '[]',
    metadata              JSONB DEFAULT '{}',
    created_at            TIMESTAMP DEFAULT NOW(),
    updated_at            TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contract_versions (
    id              SERIAL PRIMARY KEY,
    contract_id     INT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    version_number  INT DEFAULT 1,
    content         TEXT NOT NULL,
    change_notes    TEXT,
    created_by      VARCHAR(255),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contract_activities (
    id            SERIAL PRIMARY KEY,
    contract_id   INT NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL
                      CHECK (activity_type IN ('created','sent','viewed','signed','expired','renewed','commented','edited')),
    description   TEXT,
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contracts_customer_id  ON contracts(customer_id);
CREATE INDEX IF NOT EXISTS idx_contracts_status       ON contracts(status);
CREATE INDEX IF NOT EXISTS idx_contracts_end_date     ON contracts(end_date);
CREATE INDEX IF NOT EXISTS idx_contract_versions_cid  ON contract_versions(contract_id);
CREATE INDEX IF NOT EXISTS idx_contract_activities_cid ON contract_activities(contract_id);
