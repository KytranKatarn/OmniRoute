-- Phase 3 module catalog entries
-- categories: 'crm' for call-center/help-desk, 'automation' for automations-ui
INSERT INTO module_catalog (slug, name, description, category, tier_required, icon) VALUES
    ('call-center', 'Call Center', 'Telephony management with calls, escalations, and CRM integration', 'crm', 'enterprise', 'phone'),
    ('help-desk', 'Help Desk', 'Support ticket system with SLA tracking and comments', 'crm', 'business', 'life-buoy'),
    ('automations-ui', 'Workflow Builder', 'Visual workflow builder for enterprise automation', 'automation', 'enterprise', 'git-branch')
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    tier_required = EXCLUDED.tier_required,
    icon = EXCLUDED.icon;
