-- ============================================================================
-- A.R.C.H.I.E. Platform - SaaS Platform Layer
-- Migration: 030 - Core SaaS Tables (Organizations, Memberships, Modules, Domains)
-- Created: 2026-02-03
-- ============================================================================

-- Organizations
CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    owner_user_id INTEGER REFERENCES users(id),
    archie_user_id INTEGER REFERENCES users(id),
    status VARCHAR(50) DEFAULT 'provisioning'
        CHECK (status IN ('provisioning', 'active', 'suspended')),
    settings JSONB DEFAULT '{}',
    ai_config JSONB DEFAULT '{}',
    isolation_type VARCHAR(20) DEFAULT 'shared'
        CHECK (isolation_type IN ('shared', 'migrating', 'node')),
    node_id VARCHAR(255),
    migration_status VARCHAR(50),
    migrated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug);
CREATE INDEX IF NOT EXISTS idx_organizations_status ON organizations(status);
CREATE INDEX IF NOT EXISTS idx_organizations_owner ON organizations(owner_user_id);

DROP TRIGGER IF EXISTS update_organizations_updated_at ON organizations;
CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Organization Users (many-to-many)
CREATE TABLE IF NOT EXISTS org_users (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'admin', 'member', 'archie')),
    invited_at TIMESTAMP DEFAULT NOW(),
    joined_at TIMESTAMP,
    UNIQUE(org_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_org_users_org ON org_users(org_id);
CREATE INDEX IF NOT EXISTS idx_org_users_user ON org_users(user_id);

-- Organization Modules (a la carte access)
CREATE TABLE IF NOT EXISTS org_modules (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    module_key VARCHAR(100) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    config JSONB DEFAULT '{}',
    activated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, module_key)
);

CREATE INDEX IF NOT EXISTS idx_org_modules_org ON org_modules(org_id);

-- Organization Domains
CREATE TABLE IF NOT EXISTS org_domains (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    domain VARCHAR(255) NOT NULL UNIQUE,
    subdomain VARCHAR(100),
    root_domain VARCHAR(255),
    target_module VARCHAR(100),
    target_port INTEGER DEFAULT 3000,
    ssl_status VARCHAR(50) DEFAULT 'pending'
        CHECK (ssl_status IN ('pending', 'active', 'failed')),
    dns_status VARCHAR(50) DEFAULT 'pending'
        CHECK (dns_status IN ('pending', 'verified', 'failed')),
    dns_provider VARCHAR(50) DEFAULT 'hostinger'
        CHECK (dns_provider IN ('hostinger', 'cloudflare', 'manual')),
    hostinger_zone_id VARCHAR(255),
    npm_proxy_host_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    verified_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_org_domains_org ON org_domains(org_id);
CREATE INDEX IF NOT EXISTS idx_org_domains_domain ON org_domains(domain);

-- Public IP History
CREATE TABLE IF NOT EXISTS org_ip_history (
    id SERIAL PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    detected_at TIMESTAMP DEFAULT NOW()
);
