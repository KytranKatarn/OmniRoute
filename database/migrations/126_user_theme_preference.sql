-- Migration 126: User theme preference + org default theme
-- Uses existing JSONB columns (users.metadata, organizations.settings)
-- User theme_preference: NULL means "use org default", explicit value = user's choice
-- Org default_theme: fallback for users without a preference

-- Set default_theme on all orgs that don't have one
UPDATE organizations
SET settings = COALESCE(settings, '{}'::jsonb) || '{"default_theme": "lcars-classic"}'::jsonb
WHERE settings IS NULL OR NOT settings ? 'default_theme';
