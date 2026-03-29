-- Store plugin migration 002 — webhook logging + guest checkout columns.
-- All statements are idempotent. Run inside tenant schema.

-- ---------------------------------------------------------------
-- 1. Guest checkout columns on store_orders
-- ---------------------------------------------------------------

ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS customer_name  VARCHAR(255);
ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS customer_email VARCHAR(255);
ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'unpaid';

CREATE INDEX IF NOT EXISTS idx_store_orders_email ON store_orders (customer_email);

-- ---------------------------------------------------------------
-- 2. Price alias on store_order_items (guest checkout uses "price")
-- ---------------------------------------------------------------

ALTER TABLE store_order_items ADD COLUMN IF NOT EXISTS price DECIMAL(10,2);

-- ---------------------------------------------------------------
-- 3. Webhook audit log
-- ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS store_webhook_logs (
    id            SERIAL PRIMARY KEY,
    source        VARCHAR(50) NOT NULL,
    event_type    VARCHAR(100) NOT NULL,
    event_id      VARCHAR(255),
    payload       JSONB DEFAULT '{}',
    processed     BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_store_webhook_logs_source ON store_webhook_logs (source);
CREATE INDEX IF NOT EXISTS idx_store_webhook_logs_created ON store_webhook_logs (created_at);
