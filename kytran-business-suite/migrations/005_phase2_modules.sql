-- Phase 2 module catalog entries
INSERT INTO module_catalog (slug, name, description, category, tier_required, icon) VALUES
    ('appointments', 'Appointments', 'Booking and scheduling for service businesses', 'scheduling', 'business', 'calendar'),
    ('content-studio', 'Content Studio', 'AI-powered document creation with templates and export', 'marketing', 'business', 'pen-tool'),
    ('social-media', 'Social Media', 'Multi-platform scheduling, campaigns, and analytics', 'marketing', 'business', 'share-2'),
    ('website-builder', 'Website Builder', 'AI-powered website creation with pages and deployments', 'marketing', 'business', 'globe'),
    ('marketing', 'Marketing Dashboard', 'Unified analytics across CRM, social, and content', 'analytics', 'business', 'bar-chart-2')
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    tier_required = EXCLUDED.tier_required,
    icon = EXCLUDED.icon;
