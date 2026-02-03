-- ============================================================================
-- A.R.C.H.I.E. Platform - SaaS Platform Layer
-- Migration: 031 - Seed Kytran Empowerment Organization
-- Created: 2026-02-03
-- ============================================================================

-- Create org (idempotent: skip if slug exists)
INSERT INTO organizations (name, slug, owner_user_id, archie_user_id, status, settings, ai_config)
SELECT
    'Kytran Empowerment',
    'kytran-empowerment',
    (SELECT id FROM users WHERE username = 'Kytran'),
    (SELECT id FROM users WHERE username = 'admin'),
    'active',
    '{"root_domain": "kytranempowerment.com", "branding": {"primary_color": "#1a1a2e"}}'::jsonb,
    '{"personality": "professional", "role": "business_partner"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE slug = 'kytran-empowerment');

-- Add org memberships
INSERT INTO org_users (org_id, user_id, role, joined_at)
SELECT o.id, u.id, 'owner', NOW()
FROM organizations o, users u
WHERE o.slug = 'kytran-empowerment' AND u.username = 'Kytran'
ON CONFLICT (org_id, user_id) DO NOTHING;

INSERT INTO org_users (org_id, user_id, role, joined_at)
SELECT o.id, u.id, 'archie', NOW()
FROM organizations o, users u
WHERE o.slug = 'kytran-empowerment' AND u.username = 'admin'
ON CONFLICT (org_id, user_id) DO NOTHING;

-- Enable initial modules
INSERT INTO org_modules (org_id, module_key, config)
SELECT o.id, m.key, m.config
FROM organizations o,
(VALUES
    ('store_builder', '{"printful_store": "store.kytranempowerment.com"}'::jsonb),
    ('website_studio', '{"domain": "www.kytranempowerment.com"}'::jsonb),
    ('media_hub', '{"domain": "media.kytranempowerment.com"}'::jsonb),
    ('crm', '{}'::jsonb),
    ('email_manager', '{}'::jsonb),
    ('invoicing', '{}'::jsonb),
    ('scheduler', '{}'::jsonb)
) AS m(key, config)
WHERE o.slug = 'kytran-empowerment'
ON CONFLICT (org_id, module_key) DO NOTHING;

-- Register domains
INSERT INTO org_domains (org_id, domain, subdomain, root_domain, target_module, dns_provider)
SELECT o.id, d.domain, d.sub, d.root, d.target, 'hostinger'
FROM organizations o,
(VALUES
    ('dashboard.kytranempowerment.com', 'dashboard', 'kytranempowerment.com', 'dashboard'),
    ('www.kytranempowerment.com', 'www', 'kytranempowerment.com', 'website_studio'),
    ('store.kytranempowerment.com', 'store', 'kytranempowerment.com', 'store_builder'),
    ('media.kytranempowerment.com', 'media', 'kytranempowerment.com', 'media_hub')
) AS d(domain, sub, root, target)
WHERE o.slug = 'kytran-empowerment'
ON CONFLICT (domain) DO NOTHING;
