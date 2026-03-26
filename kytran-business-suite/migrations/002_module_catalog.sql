-- Migration 002: Module catalog and tenant module assignments
-- Idempotent: uses IF NOT EXISTS and ON CONFLICT DO UPDATE

CREATE TABLE IF NOT EXISTS module_catalog (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    category VARCHAR(50) NOT NULL CHECK (category IN (
        'crm', 'finance', 'ecommerce', 'scheduling',
        'marketing', 'automation', 'analytics'
    )),
    tier_required VARCHAR(20) NOT NULL DEFAULT 'free' CHECK (tier_required IN ('free', 'business', 'enterprise')),
    price_monthly DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    icon VARCHAR(100),
    dependencies JSONB NOT NULL DEFAULT '[]',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_modules (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    module_slug VARCHAR(100) NOT NULL REFERENCES module_catalog(slug) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    source VARCHAR(30) NOT NULL DEFAULT 'tier_included' CHECK (source IN (
        'tier_included', 'addon_purchase', 'trial', 'manual'
    )),
    activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ,
    UNIQUE (tenant_id, module_slug)
);

-- Seed Phase 1 modules (idempotent)
INSERT INTO module_catalog (slug, name, description, version, category, tier_required, price_monthly, icon, dependencies)
VALUES
    ('crm',          'CRM',           'Contact and relationship management',    '1.0.0', 'crm',        'free',     0.00, 'users',          '[]'),
    ('invoicing',    'Invoicing',     'Invoice creation and payment tracking',  '1.0.0', 'finance',    'free',     0.00, 'file-invoice',   '[]'),
    ('store',        'Store Builder', 'E-commerce storefront and product mgmt', '1.0.0', 'ecommerce',  'business', 0.00, 'shopping-cart',  '["crm"]'),
    ('automations',  'Automations',   'Workflow and task automation engine',    '1.0.0', 'automation', 'business', 0.00, 'bolt',           '[]'),
    ('appointments', 'Appointments',  'Scheduling and booking management',      '1.0.0', 'scheduling', 'free',     0.00, 'calendar-check', '[]')
ON CONFLICT (slug) DO UPDATE SET
    name         = EXCLUDED.name,
    description  = EXCLUDED.description,
    version      = EXCLUDED.version,
    category     = EXCLUDED.category,
    tier_required = EXCLUDED.tier_required,
    icon         = EXCLUDED.icon,
    dependencies = EXCLUDED.dependencies,
    is_active    = EXCLUDED.is_active;
