-- Store plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

CREATE TABLE IF NOT EXISTS store_categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    parent_id   INTEGER REFERENCES store_categories(id),
    sort_order  INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS store_products (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    sku               VARCHAR(100),
    price             DECIMAL(10,2) NOT NULL,
    compare_at_price  DECIMAL(10,2),
    inventory_count   INTEGER DEFAULT 0,
    status            VARCHAR(20) DEFAULT 'active'
                          CHECK (status IN ('active', 'draft', 'archived')),
    category          VARCHAR(100),
    images            JSONB DEFAULT '[]',
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS store_orders (
    id               SERIAL PRIMARY KEY,
    order_number     VARCHAR(50) UNIQUE,
    customer_id      INTEGER,
    status           VARCHAR(20) DEFAULT 'pending'
                         CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled', 'refunded')),
    subtotal         DECIMAL(10,2) DEFAULT 0,
    tax              DECIMAL(10,2) DEFAULT 0,
    shipping         DECIMAL(10,2) DEFAULT 0,
    total            DECIMAL(10,2) DEFAULT 0,
    shipping_address JSONB DEFAULT '{}',
    tracking_number  VARCHAR(255),
    notes            TEXT,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS store_order_items (
    id           SERIAL PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE,
    product_id   INTEGER REFERENCES store_products(id),
    product_name VARCHAR(255) NOT NULL,
    quantity     INTEGER DEFAULT 1,
    unit_price   DECIMAL(10,2) NOT NULL,
    total        DECIMAL(10,2) NOT NULL,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_store_products_status   ON store_products (status);
CREATE INDEX IF NOT EXISTS idx_store_products_sku      ON store_products (sku);
CREATE INDEX IF NOT EXISTS idx_store_orders_customer   ON store_orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_store_orders_status     ON store_orders (status);
CREATE INDEX IF NOT EXISTS idx_store_order_items_order ON store_order_items (order_id);
