-- Stripe Core billing tables
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/204_billing_core.sql

CREATE TABLE IF NOT EXISTS billing_customers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    stripe_customer_id VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(256),
    name VARCHAR(256),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_customers_stripe ON billing_customers(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_customers_user ON billing_customers(user_id);

CREATE TABLE IF NOT EXISTS billing_events (
    id SERIAL PRIMARY KEY,
    stripe_event_id VARCHAR(64) NOT NULL UNIQUE,
    event_type VARCHAR(128) NOT NULL,
    data JSONB NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    handler_result TEXT,
    received_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_events_type ON billing_events(event_type);
CREATE INDEX IF NOT EXISTS idx_billing_events_received ON billing_events(received_at);

CREATE TABLE IF NOT EXISTS billing_products (
    id SERIAL PRIMARY KEY,
    stripe_product_id VARCHAR(64) NOT NULL,
    stripe_price_id VARCHAR(64) NOT NULL UNIQUE,
    module VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) DEFAULT 'usd',
    billing_interval VARCHAR(16) DEFAULT 'month' CHECK(billing_interval IN ('month', 'year', 'one_time')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_products_module ON billing_products(module);
