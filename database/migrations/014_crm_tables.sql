-- ============================================================================
-- Migration 014: CRM Tables
-- Purpose: Customer management with subscription tracking for Business Tools
-- Created: 2026-01-17
-- ============================================================================

-- Customer profiles with order history
CREATE TABLE IF NOT EXISTS crm_customers (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(50),
    company VARCHAR(200),
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    postal_code VARCHAR(20),
    country VARCHAR(100) DEFAULT 'Canada',
    source VARCHAR(50) DEFAULT 'manual', -- 'store', 'call_center', 'manual', 'import'
    subscription_tier VARCHAR(50), -- links to subscription_tiers.name
    subscription_status VARCHAR(50) DEFAULT 'none', -- 'none', 'active', 'cancelled', 'expired'
    subscription_id INTEGER, -- links to user_subscriptions.id
    tags TEXT[] DEFAULT '{}',
    notes TEXT,
    total_orders INTEGER DEFAULT 0,
    total_spent DECIMAL(10,2) DEFAULT 0.00,
    last_order_date TIMESTAMP,
    last_interaction_date TIMESTAMP,
    lifetime_value DECIMAL(10,2) DEFAULT 0.00,
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Customer interactions log
CREATE TABLE IF NOT EXISTS crm_interactions (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES crm_customers(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50) NOT NULL, -- 'email', 'call', 'note', 'order', 'support', 'subscription'
    subject VARCHAR(255),
    content TEXT,
    metadata JSONB DEFAULT '{}', -- additional data like call duration, order id, etc.
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Customer segments for marketing
CREATE TABLE IF NOT EXISTS crm_segments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    filter_criteria JSONB DEFAULT '{}', -- dynamic filter rules
    customer_count INTEGER DEFAULT 0,
    is_dynamic BOOLEAN DEFAULT TRUE, -- auto-update count
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Segment membership (for static segments or caching)
CREATE TABLE IF NOT EXISTS crm_segment_members (
    id SERIAL PRIMARY KEY,
    segment_id INTEGER REFERENCES crm_segments(id) ON DELETE CASCADE,
    customer_id INTEGER REFERENCES crm_customers(id) ON DELETE CASCADE,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(segment_id, customer_id)
);

-- Customer activity log (for analytics)
CREATE TABLE IF NOT EXISTS crm_activity_log (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES crm_customers(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL, -- 'page_view', 'login', 'purchase', 'support_ticket'
    activity_data JSONB DEFAULT '{}',
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Import history
CREATE TABLE IF NOT EXISTS crm_imports (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255),
    total_rows INTEGER DEFAULT 0,
    imported_rows INTEGER DEFAULT 0,
    failed_rows INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]',
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_crm_customers_email ON crm_customers(email);
CREATE INDEX IF NOT EXISTS idx_crm_customers_source ON crm_customers(source);
CREATE INDEX IF NOT EXISTS idx_crm_customers_subscription ON crm_customers(subscription_status);
CREATE INDEX IF NOT EXISTS idx_crm_customers_tags ON crm_customers USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_crm_customers_created ON crm_customers(created_at);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_customer ON crm_interactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_type ON crm_interactions(interaction_type);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_created ON crm_interactions(created_at);
CREATE INDEX IF NOT EXISTS idx_crm_activity_customer ON crm_activity_log(customer_id);
CREATE INDEX IF NOT EXISTS idx_crm_activity_type ON crm_activity_log(activity_type);

-- Function to update customer stats
CREATE OR REPLACE FUNCTION update_crm_customer_stats()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE crm_customers
    SET last_interaction_date = NOW(),
        updated_at = NOW()
    WHERE id = NEW.customer_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update customer on interaction
DROP TRIGGER IF EXISTS trigger_crm_interaction_update ON crm_interactions;
CREATE TRIGGER trigger_crm_interaction_update
    AFTER INSERT ON crm_interactions
    FOR EACH ROW
    EXECUTE FUNCTION update_crm_customer_stats();

-- Insert default segments
INSERT INTO crm_segments (name, description, filter_criteria, is_dynamic) VALUES
    ('All Customers', 'All active customers', '{"is_active": true}', true),
    ('Subscribers', 'Customers with active subscriptions', '{"subscription_status": "active"}', true),
    ('High Value', 'Customers with lifetime value > $500', '{"lifetime_value_gt": 500}', true),
    ('New This Month', 'Customers created this month', '{"created_this_month": true}', true),
    ('No Orders', 'Customers who haven''t ordered yet', '{"total_orders": 0}', true)
ON CONFLICT DO NOTHING;

-- Grant permissions
GRANT ALL ON crm_customers TO archie;
GRANT ALL ON crm_interactions TO archie;
GRANT ALL ON crm_segments TO archie;
GRANT ALL ON crm_segment_members TO archie;
GRANT ALL ON crm_activity_log TO archie;
GRANT ALL ON crm_imports TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Add comment
COMMENT ON TABLE crm_customers IS 'CRM customer profiles with subscription and order tracking';
COMMENT ON TABLE crm_interactions IS 'Log of all customer interactions (calls, emails, notes, orders)';
COMMENT ON TABLE crm_segments IS 'Customer segments for marketing and filtering';
