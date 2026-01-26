-- Migration 018: User Data Isolation & Subscription Tiers
-- Purpose: Add per-user data isolation and subscription management
-- Date: 2026-01-12

-- ============================================================================
-- PART 1: Add user_id to tables needing isolation
-- ============================================================================

-- Conversations table (for Archie Chat)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversations' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE conversations ADD COLUMN user_id INTEGER REFERENCES users(id);
        CREATE INDEX idx_conversations_user_id ON conversations(user_id);
        RAISE NOTICE 'Added user_id to conversations table';
    ELSE
        RAISE NOTICE 'user_id already exists in conversations table';
    END IF;
END $$;

-- Website Builder Projects (create if not exists)
CREATE TABLE IF NOT EXISTS website_builder_projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    template VARCHAR(100),
    settings JSONB DEFAULT '{}',
    published BOOLEAN DEFAULT FALSE,
    published_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add user_id if table existed without it
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'website_builder_projects' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE website_builder_projects ADD COLUMN user_id INTEGER REFERENCES users(id);
        CREATE INDEX idx_website_builder_projects_user_id ON website_builder_projects(user_id);
        RAISE NOTICE 'Added user_id to website_builder_projects table';
    END IF;
END $$;

-- Website Builder Pages
CREATE TABLE IF NOT EXISTS website_builder_pages (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES website_builder_projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255),
    content JSONB DEFAULT '{}',
    html_content TEXT,
    css_content TEXT,
    js_content TEXT,
    is_homepage BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add user_id if table existed without it
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'website_builder_pages' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE website_builder_pages ADD COLUMN user_id INTEGER REFERENCES users(id);
        CREATE INDEX idx_website_builder_pages_user_id ON website_builder_pages(user_id);
        RAISE NOTICE 'Added user_id to website_builder_pages table';
    END IF;
END $$;

-- Code Editor Sessions
CREATE TABLE IF NOT EXISTS code_editor_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) NOT NULL,
    name VARCHAR(255),
    workspace_path TEXT,
    settings JSONB DEFAULT '{}',
    last_active_file TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_code_editor_sessions_user_id ON code_editor_sessions(user_id);

-- Code Editor Files
CREATE TABLE IF NOT EXISTS code_editor_files (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES code_editor_sessions(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) NOT NULL,
    file_path TEXT NOT NULL,
    content TEXT,
    is_open BOOLEAN DEFAULT FALSE,
    cursor_position JSONB,
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_code_editor_files_user_id ON code_editor_files(user_id);
CREATE INDEX IF NOT EXISTS idx_code_editor_files_session_id ON code_editor_files(session_id);

-- ============================================================================
-- PART 2: Subscription Tiers Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS subscription_tiers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    description TEXT,
    price_monthly DECIMAL(10,2) DEFAULT 0,
    price_yearly DECIMAL(10,2) DEFAULT 0,
    features JSONB DEFAULT '[]',
    limits JSONB DEFAULT '{}',
    role_level INTEGER DEFAULT 10,
    color VARCHAR(20) DEFAULT '#00ff41',
    sort_order INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default subscription tiers
INSERT INTO subscription_tiers (name, display_name, description, price_monthly, price_yearly, role_level, features, limits, color, sort_order) VALUES
('free', 'Free', 'Basic access to ARCHIE platform', 0, 0, 10,
 '["Archie Chat (basic)", "Code Editor", "1 App Builder project", "Team Directory access"]',
 '{"app_projects": 1, "website_projects": 0, "api_calls_daily": 100, "storage_mb": 100}',
 '#6e7681', 1),
('pro', 'Pro', 'Enhanced features for power users', 9.99, 99.99, 20,
 '["Unlimited Archie Chat", "App Builder (10 projects)", "Website Builder (5 projects)", "API access", "Priority support"]',
 '{"app_projects": 10, "website_projects": 5, "api_calls_daily": 5000, "storage_mb": 5000}',
 '#00ff41', 2),
('business', 'Business', 'Full platform access for teams', 29.99, 299.99, 20,
 '["Everything in Pro", "Unlimited projects", "Custom integrations", "Team collaboration", "Advanced analytics", "Dedicated support"]',
 '{"app_projects": -1, "website_projects": -1, "api_calls_daily": 50000, "storage_mb": 50000}',
 '#39ff14', 3),
('enterprise', 'Enterprise', 'Custom solutions for organizations', 99.99, 999.99, 20,
 '["Everything in Business", "Custom AI training", "SLA guarantee", "Dedicated infrastructure", "White-label options", "24/7 priority support"]',
 '{"app_projects": -1, "website_projects": -1, "api_calls_daily": -1, "storage_mb": -1}',
 '#ffd700', 4)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    price_monthly = EXCLUDED.price_monthly,
    price_yearly = EXCLUDED.price_yearly,
    features = EXCLUDED.features,
    limits = EXCLUDED.limits,
    color = EXCLUDED.color,
    sort_order = EXCLUDED.sort_order,
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================================
-- PART 3: User Activity Log Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_activity_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username VARCHAR(255),
    action VARCHAR(100) NOT NULL,
    module VARCHAR(100),
    resource_type VARCHAR(100),
    resource_id INTEGER,
    details JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    session_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_activity_user_id ON user_activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activity_created_at ON user_activity_log(created_at);
CREATE INDEX IF NOT EXISTS idx_user_activity_action ON user_activity_log(action);
CREATE INDEX IF NOT EXISTS idx_user_activity_module ON user_activity_log(module);

-- ============================================================================
-- PART 4: User Subscriptions Table (Link users to tiers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    tier_id INTEGER REFERENCES subscription_tiers(id),
    status VARCHAR(50) DEFAULT 'active',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    payment_method VARCHAR(100),
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_id ON user_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_tier_id ON user_subscriptions(tier_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_status ON user_subscriptions(status);

-- ============================================================================
-- PART 5: Add subscription_tier column to users if not exists
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'subscription_tier'
    ) THEN
        ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(50) DEFAULT 'free';
        RAISE NOTICE 'Added subscription_tier to users table';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'subscription_status'
    ) THEN
        ALTER TABLE users ADD COLUMN subscription_status VARCHAR(50) DEFAULT 'active';
        RAISE NOTICE 'Added subscription_status to users table';
    END IF;
END $$;

-- ============================================================================
-- PART 6: Create views for easy querying
-- ============================================================================

-- User stats view
CREATE OR REPLACE VIEW v_user_stats AS
SELECT
    u.id,
    u.username,
    u.email,
    u.role,
    COALESCE(u.subscription_tier, 'free') as subscription_tier,
    u.is_admin,
    u.is_super_admin,
    u.created_at,
    u.last_login,
    (SELECT COUNT(*) FROM conversations WHERE user_id = u.id) as conversation_count,
    (SELECT COUNT(*) FROM app_builder_projects WHERE user_id = u.id) as app_project_count,
    (SELECT COUNT(*) FROM website_builder_projects WHERE user_id = u.id) as website_project_count,
    (SELECT COUNT(*) FROM user_activity_log WHERE user_id = u.id) as activity_count
FROM users u;

-- Activity summary view
CREATE OR REPLACE VIEW v_activity_summary AS
SELECT
    DATE(created_at) as date,
    module,
    action,
    COUNT(*) as count
FROM user_activity_log
GROUP BY DATE(created_at), module, action
ORDER BY date DESC, count DESC;

-- ============================================================================
-- Complete
-- ============================================================================

SELECT 'Migration 018: User Data Isolation completed successfully' as status;
