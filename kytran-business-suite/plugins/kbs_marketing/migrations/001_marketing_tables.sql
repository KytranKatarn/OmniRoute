-- Marketing Dashboard plugin tables
-- Runs inside tenant schema (search_path already set by migration runner)

CREATE TABLE IF NOT EXISTS marketing_campaigns (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    status      VARCHAR(20)  DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'paused', 'completed')),
    channel     VARCHAR(50)
                CHECK (channel IN ('email', 'social', 'content', 'multi-channel')),
    start_date  DATE,
    end_date    DATE,
    budget      DECIMAL(10, 2),
    spend       DECIMAL(10, 2) DEFAULT 0,
    goal_type   VARCHAR(50),
    goal_value  DECIMAL(10, 2),
    metadata    JSONB          DEFAULT '{}',
    created_at  TIMESTAMP      DEFAULT NOW(),
    updated_at  TIMESTAMP      DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marketing_leads (
    id          SERIAL PRIMARY KEY,
    customer_id INT,
    source      VARCHAR(100),
    score       INT            DEFAULT 0,
    stage       VARCHAR(50)    DEFAULT 'new'
                CHECK (stage IN ('new', 'contacted', 'qualified', 'proposal', 'won', 'lost')),
    notes       TEXT,
    metadata    JSONB          DEFAULT '{}',
    created_at  TIMESTAMP      DEFAULT NOW(),
    updated_at  TIMESTAMP      DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_status
    ON marketing_campaigns (status);

CREATE INDEX IF NOT EXISTS idx_marketing_leads_customer_id
    ON marketing_leads (customer_id);

CREATE INDEX IF NOT EXISTS idx_marketing_leads_stage
    ON marketing_leads (stage);

CREATE INDEX IF NOT EXISTS idx_marketing_leads_score
    ON marketing_leads (score);
