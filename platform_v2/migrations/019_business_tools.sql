-- ============================================================================
-- A.R.C.H.I.E. Platform - Business Tools Schema
-- Migration: 019 - Business Tools (Website Studio, Store Builder, Call Center)
-- Created: 2026-01-12
-- ============================================================================

-- ============================================================================
-- USER INTEGRATIONS (API credentials per user)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_integrations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    service VARCHAR(50) NOT NULL,  -- github, cloudflare, vercel, stripe, paypal, twilio, telnyx
    credentials JSONB DEFAULT '{}',  -- encrypted API keys/tokens
    settings JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'error', 'pending')),
    last_verified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, service)
);

CREATE INDEX IF NOT EXISTS idx_user_integrations_user ON user_integrations(user_id);
CREATE INDEX IF NOT EXISTS idx_user_integrations_service ON user_integrations(service);

-- ============================================================================
-- USER STORES (E-commerce stores per user)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_stores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE,
    description TEXT,
    logo_url TEXT,
    banner_url TEXT,
    settings JSONB DEFAULT '{}',  -- theme, currency, shipping, tax settings
    payment_config JSONB DEFAULT '{}',  -- payment provider settings (encrypted)
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    address JSONB DEFAULT '{}',
    social_links JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'paused', 'closed')),
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_stores_user ON user_stores(user_id);
CREATE INDEX IF NOT EXISTS idx_user_stores_slug ON user_stores(slug);
CREATE INDEX IF NOT EXISTS idx_user_stores_status ON user_stores(status);

-- ============================================================================
-- STORE CATEGORIES
-- ============================================================================

CREATE TABLE IF NOT EXISTS store_categories (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES user_stores(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100),
    description TEXT,
    image_url TEXT,
    parent_id INTEGER REFERENCES store_categories(id) ON DELETE SET NULL,
    sort_order INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'active' CHECK (status IN ('active', 'hidden')),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_store_categories_store ON store_categories(store_id);
CREATE INDEX IF NOT EXISTS idx_store_categories_parent ON store_categories(parent_id);

-- ============================================================================
-- STORE PRODUCTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS store_products (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES user_stores(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES store_categories(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255),
    description TEXT,
    short_description VARCHAR(500),
    sku VARCHAR(100),
    price DECIMAL(10,2) NOT NULL,
    compare_at_price DECIMAL(10,2),  -- original price for showing discounts
    cost_price DECIMAL(10,2),  -- cost for profit tracking
    images JSONB DEFAULT '[]',  -- array of image URLs
    inventory INTEGER DEFAULT 0,
    track_inventory BOOLEAN DEFAULT true,
    allow_backorder BOOLEAN DEFAULT false,
    weight DECIMAL(10,2),  -- in grams
    dimensions JSONB DEFAULT '{}',  -- length, width, height
    variants JSONB DEFAULT '[]',  -- size, color, etc.
    attributes JSONB DEFAULT '{}',  -- custom attributes
    seo_title VARCHAR(255),
    seo_description VARCHAR(500),
    tags TEXT[],
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'hidden', 'archived')),
    featured BOOLEAN DEFAULT false,
    sort_order INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    sold_count INTEGER DEFAULT 0,
    printful_id VARCHAR(100),  -- for Printful integration
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_store_products_store ON store_products(store_id);
CREATE INDEX IF NOT EXISTS idx_store_products_user ON store_products(user_id);
CREATE INDEX IF NOT EXISTS idx_store_products_category ON store_products(category_id);
CREATE INDEX IF NOT EXISTS idx_store_products_status ON store_products(status);
CREATE INDEX IF NOT EXISTS idx_store_products_sku ON store_products(sku);
CREATE INDEX IF NOT EXISTS idx_store_products_featured ON store_products(featured, sort_order);

-- ============================================================================
-- STORE ORDERS
-- ============================================================================

CREATE TABLE IF NOT EXISTS store_orders (
    id SERIAL PRIMARY KEY,
    store_id INTEGER REFERENCES user_stores(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- store owner
    order_number VARCHAR(50) UNIQUE,
    customer_email VARCHAR(255) NOT NULL,
    customer_name VARCHAR(255),
    customer_phone VARCHAR(50),
    items JSONB NOT NULL DEFAULT '[]',  -- array of {product_id, name, sku, quantity, price, variant}
    subtotal DECIMAL(10,2) NOT NULL,
    tax DECIMAL(10,2) DEFAULT 0,
    shipping_cost DECIMAL(10,2) DEFAULT 0,
    discount DECIMAL(10,2) DEFAULT 0,
    total DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN (
        'pending', 'confirmed', 'processing', 'shipped', 'delivered',
        'cancelled', 'refunded', 'failed'
    )),
    payment_status VARCHAR(50) DEFAULT 'pending' CHECK (payment_status IN (
        'pending', 'paid', 'failed', 'refunded', 'partially_refunded'
    )),
    payment_method VARCHAR(50),  -- stripe, paypal, etc.
    payment_id VARCHAR(255),  -- transaction ID from payment provider
    shipping_address JSONB DEFAULT '{}',
    billing_address JSONB DEFAULT '{}',
    shipping_method VARCHAR(100),
    tracking_number VARCHAR(255),
    tracking_url TEXT,
    notes TEXT,
    customer_notes TEXT,
    metadata JSONB DEFAULT '{}',
    shipped_at TIMESTAMP,
    delivered_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_store_orders_store ON store_orders(store_id);
CREATE INDEX IF NOT EXISTS idx_store_orders_user ON store_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_store_orders_customer ON store_orders(customer_email);
CREATE INDEX IF NOT EXISTS idx_store_orders_status ON store_orders(status);
CREATE INDEX IF NOT EXISTS idx_store_orders_payment ON store_orders(payment_status);
CREATE INDEX IF NOT EXISTS idx_store_orders_date ON store_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_store_orders_number ON store_orders(order_number);

-- ============================================================================
-- ORDER ITEMS (normalized for better querying)
-- ============================================================================

CREATE TABLE IF NOT EXISTS store_order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES store_orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES store_products(id) ON DELETE SET NULL,
    product_name VARCHAR(255) NOT NULL,
    product_sku VARCHAR(100),
    variant_info JSONB DEFAULT '{}',
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON store_order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON store_order_items(product_id);

-- ============================================================================
-- USER PHONE NUMBERS (for Call Center)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_phone_numbers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    provider_id UUID REFERENCES providers(id) ON DELETE SET NULL,
    phone_number VARCHAR(20) NOT NULL,
    friendly_name VARCHAR(100),
    country_code VARCHAR(5),
    capabilities JSONB DEFAULT '{}',  -- voice, sms, mms, fax
    monthly_cost DECIMAL(10,4),
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'pending', 'released')),
    forwarding_number VARCHAR(20),  -- optional forwarding
    ai_agent_enabled BOOLEAN DEFAULT true,
    ai_agent_config JSONB DEFAULT '{}',  -- agent personality, knowledge base, etc.
    business_hours JSONB DEFAULT '{}',  -- when AI should answer
    voicemail_enabled BOOLEAN DEFAULT true,
    voicemail_greeting_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_phone_numbers_user ON user_phone_numbers(user_id);
CREATE INDEX IF NOT EXISTS idx_user_phone_numbers_provider ON user_phone_numbers(provider_id);
CREATE INDEX IF NOT EXISTS idx_user_phone_numbers_number ON user_phone_numbers(phone_number);
CREATE INDEX IF NOT EXISTS idx_user_phone_numbers_status ON user_phone_numbers(status);

-- ============================================================================
-- EXTEND PROVIDERS TABLE (add user_id for per-user providers)
-- ============================================================================

-- Add user_id column to providers (NULL = system/admin provider)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'providers' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE providers ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
        CREATE INDEX IF NOT EXISTS idx_providers_user ON providers(user_id);
    END IF;
END $$;

-- ============================================================================
-- EXTEND CONVERSATIONS TABLE (add user_id for per-user filtering)
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversations' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE conversations ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
    END IF;
END $$;

-- ============================================================================
-- EXTEND ESCALATIONS TABLE (ensure user filtering works)
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'escalations' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE escalations ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_escalations_user ON escalations(user_id);
    END IF;
END $$;

-- ============================================================================
-- WEBSITE DEPLOYMENT TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS website_deployments (
    id SERIAL PRIMARY KEY,
    project_id INTEGER,  -- references website_builder_projects
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    deployment_type VARCHAR(50) CHECK (deployment_type IN ('github_pages', 'vercel', 'netlify', 'custom')),
    repository_url TEXT,
    deployment_url TEXT,
    custom_domain VARCHAR(255),
    ssl_enabled BOOLEAN DEFAULT false,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN (
        'pending', 'building', 'deployed', 'failed', 'inactive'
    )),
    last_deployed_at TIMESTAMP,
    build_logs TEXT,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_deployments_project ON website_deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_website_deployments_user ON website_deployments(user_id);
CREATE INDEX IF NOT EXISTS idx_website_deployments_status ON website_deployments(status);

-- ============================================================================
-- TRIGGERS FOR UPDATED_AT
-- ============================================================================

-- Apply updated_at trigger to new tables
DROP TRIGGER IF EXISTS update_user_integrations_updated_at ON user_integrations;
CREATE TRIGGER update_user_integrations_updated_at BEFORE UPDATE ON user_integrations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_stores_updated_at ON user_stores;
CREATE TRIGGER update_user_stores_updated_at BEFORE UPDATE ON user_stores
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_store_products_updated_at ON store_products;
CREATE TRIGGER update_store_products_updated_at BEFORE UPDATE ON store_products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_store_orders_updated_at ON store_orders;
CREATE TRIGGER update_store_orders_updated_at BEFORE UPDATE ON store_orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_phone_numbers_updated_at ON user_phone_numbers;
CREATE TRIGGER update_user_phone_numbers_updated_at BEFORE UPDATE ON user_phone_numbers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_website_deployments_updated_at ON website_deployments;
CREATE TRIGGER update_website_deployments_updated_at BEFORE UPDATE ON website_deployments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- ORDER NUMBER SEQUENCE
-- ============================================================================

CREATE SEQUENCE IF NOT EXISTS store_order_number_seq START 10001;

-- Function to generate order numbers
CREATE OR REPLACE FUNCTION generate_order_number()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.order_number IS NULL THEN
        NEW.order_number := 'ORD-' || to_char(NOW(), 'YYYYMM') || '-' ||
                           lpad(nextval('store_order_number_seq')::text, 6, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS generate_order_number_trigger ON store_orders;
CREATE TRIGGER generate_order_number_trigger
    BEFORE INSERT ON store_orders
    FOR EACH ROW EXECUTE FUNCTION generate_order_number();

-- ============================================================================
-- UPDATE PRODUCT SOLD COUNT TRIGGER
-- ============================================================================

CREATE OR REPLACE FUNCTION update_product_sold_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE store_products
        SET sold_count = sold_count + NEW.quantity
        WHERE id = NEW.product_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_product_sold_count_trigger ON store_order_items;
CREATE TRIGGER update_product_sold_count_trigger
    AFTER INSERT ON store_order_items
    FOR EACH ROW EXECUTE FUNCTION update_product_sold_count();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Store dashboard stats view
CREATE OR REPLACE VIEW store_dashboard_stats AS
SELECT
    s.id as store_id,
    s.user_id,
    s.name as store_name,
    COUNT(DISTINCT p.id) as total_products,
    COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'active') as active_products,
    COUNT(DISTINCT o.id) as total_orders,
    COUNT(DISTINCT o.id) FILTER (WHERE o.status = 'pending') as pending_orders,
    COALESCE(SUM(o.total) FILTER (WHERE o.payment_status = 'paid'), 0) as total_revenue,
    COALESCE(SUM(o.total) FILTER (WHERE o.payment_status = 'paid' AND o.created_at > NOW() - INTERVAL '30 days'), 0) as revenue_30d
FROM user_stores s
LEFT JOIN store_products p ON s.id = p.store_id
LEFT JOIN store_orders o ON s.id = o.store_id
GROUP BY s.id, s.user_id, s.name;

-- Call center stats view
CREATE OR REPLACE VIEW call_center_user_stats AS
SELECT
    pn.user_id,
    COUNT(DISTINCT pn.id) as total_numbers,
    COUNT(DISTINCT c.id) as total_calls,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status = 'active') as active_calls,
    COUNT(DISTINCT e.id) as total_escalations,
    COUNT(DISTINCT e.id) FILTER (WHERE e.resolved_at IS NULL) as pending_escalations,
    AVG(c.customer_satisfaction) as avg_satisfaction
FROM user_phone_numbers pn
LEFT JOIN conversations c ON c.called_number = pn.phone_number OR c.caller_number = pn.phone_number
LEFT JOIN escalations e ON e.conversation_id = c.id
GROUP BY pn.user_id;

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Log migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('019', 'Business Tools - Website Studio, Store Builder, Call Center', NOW())
ON CONFLICT (version) DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 019 - Business Tools completed successfully';
    RAISE NOTICE '   Tables created: user_integrations, user_stores, store_categories,';
    RAISE NOTICE '   store_products, store_orders, store_order_items, user_phone_numbers,';
    RAISE NOTICE '   website_deployments';
    RAISE NOTICE '   Extended: providers, conversations, escalations (added user_id)';
END $$;
