-- A.R.C.H.I.E. - Initial Database Schema
-- PostgreSQL 16

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- System configuration
CREATE TABLE IF NOT EXISTS system_config (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) UNIQUE NOT NULL,
    value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER
);

-- Service status tracking
CREATE TABLE IF NOT EXISTS service_status (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) UNIQUE NOT NULL,
    status VARCHAR(50) DEFAULT 'unknown',
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    metadata JSONB
);

-- ============================================================================
-- AUTHENTICATION & USERS
-- ============================================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    last_login_ip VARCHAR(50),
    metadata JSONB
);

-- Sessions
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- User permissions (role-based access control)
CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    tool_name VARCHAR(100),
    can_access BOOLEAN DEFAULT FALSE,
    can_edit BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    can_admin BOOLEAN DEFAULT FALSE,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER REFERENCES users(id)
);

-- ============================================================================
-- AUDIT & LOGGING
-- ============================================================================

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(255) NOT NULL,
    tool_name VARCHAR(100),
    resource_type VARCHAR(100),
    resource_id INTEGER,
    details TEXT,
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

-- ============================================================================
-- PROJECTS & CONTENT
-- ============================================================================

-- Projects (websites, games, apps)
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL,  -- 'website', 'game', 'app'
    status VARCHAR(50) DEFAULT 'active',
    description TEXT,
    data JSONB,
    file_path TEXT,
    preview_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deployed_at TIMESTAMP,
    metadata JSONB
);

-- Client websites (for Site Manager)
CREATE TABLE IF NOT EXISTS client_sites (
    id SERIAL PRIMARY KEY,
    client_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE,
    repo_name VARCHAR(255) UNIQUE,
    github_url TEXT,
    template VARCHAR(100),
    plan VARCHAR(50),
    monthly_price DECIMAL(10,2),
    status VARCHAR(50) DEFAULT 'active',
    icon VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_deployed TIMESTAMP,
    last_updated VARCHAR(100),
    is_client BOOLEAN DEFAULT TRUE,
    metadata JSONB
);

-- Deployments
CREATE TABLE IF NOT EXISTS deployments (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    site_id INTEGER REFERENCES client_sites(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    version VARCHAR(50),
    status VARCHAR(50) DEFAULT 'pending',
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deploy_url TEXT,
    commit_hash VARCHAR(255),
    deploy_log TEXT,
    metadata JSONB
);

-- ============================================================================
-- AI & IMPROVEMENTS
-- ============================================================================

-- Self-improvement proposals
CREATE TABLE IF NOT EXISTS improvement_proposals (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    priority VARCHAR(50) DEFAULT 'medium',
    status VARCHAR(50) DEFAULT 'proposed',
    proposed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    proposed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    implemented_at TIMESTAMP,
    code_changes TEXT,
    test_results TEXT,
    metadata JSONB
);

-- AI conversations (for Code Editor)
CREATE TABLE IF NOT EXISTS ai_conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    tool_name VARCHAR(100),
    conversation_id VARCHAR(255),
    message TEXT,
    response TEXT,
    model VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Users
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Sessions
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Audit log
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- Projects
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_type ON projects(type);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- Client sites
CREATE INDEX IF NOT EXISTS idx_sites_domain ON client_sites(domain);
CREATE INDEX IF NOT EXISTS idx_sites_status ON client_sites(status);

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert system configuration defaults
INSERT INTO system_config (key, value, description) VALUES
    ('platform_version', '2.0.0', 'A.R.C.H.I.E. platform version'),
    ('maintenance_mode', 'false', 'System maintenance mode'),
    ('allow_registration', 'false', 'Allow new user registration')
ON CONFLICT (key) DO NOTHING;

-- Insert service status placeholders
INSERT INTO service_status (service_name, status) VALUES
    ('database', 'online'),
    ('platform', 'starting'),
    ('ai_bridge', 'unknown'),
    ('code_server', 'unknown')
ON CONFLICT (service_name) DO NOTHING;

-- ============================================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for projects table
DROP TRIGGER IF EXISTS update_projects_updated_at ON projects;
CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to update session last_activity
CREATE OR REPLACE FUNCTION update_session_activity()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_activity = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for sessions table
DROP TRIGGER IF EXISTS update_sessions_activity ON sessions;
CREATE TRIGGER update_sessions_activity
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_session_activity();

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ A.R.C.H.I.E. database schema created successfully!';
    RAISE NOTICE '📊 Tables: users, sessions, projects, client_sites, deployments, audit_log';
    RAISE NOTICE '🔐 Ready for authentication and authorization';
    RAISE NOTICE '🚀 Database initialized';
END $$;
