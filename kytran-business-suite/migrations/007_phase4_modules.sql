-- Phase 4 module catalog entries
INSERT INTO module_catalog (slug, name, description, category, tier_required, icon) VALUES
    ('contracts', 'Contracts & Legal', 'Contract templates, versioning, e-signatures, and renewal management', 'finance', 'enterprise', 'file-signature'),
    ('accounting', 'Accounting', 'Chart of accounts, transactions, expenses, P&L reports with QuickBooks-familiar layout', 'finance', 'business', 'calculator')
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    tier_required = EXCLUDED.tier_required,
    icon = EXCLUDED.icon;
