-- Migration 382: Partner Profiles Table
-- Creates partner_profiles table for partner/collaborator system
-- Adds FK to user_invites for linking invites to partner profiles

CREATE TABLE IF NOT EXISTS partner_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    npm_proxy_host_id INTEGER,
    fleet_node_id INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL,
    onboarding_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_partner_profiles_user_id ON partner_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_partner_profiles_slug ON partner_profiles(slug);
CREATE INDEX IF NOT EXISTS idx_partner_profiles_invited_by ON partner_profiles(invited_by);

-- Add FK to user_invites to link invites to partner profiles
ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS partner_profile_id INTEGER REFERENCES partner_profiles(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_user_invites_partner_profile_id ON user_invites(partner_profile_id);

-- Verify migration
SELECT 'Migration 382 applied successfully' AS status;
