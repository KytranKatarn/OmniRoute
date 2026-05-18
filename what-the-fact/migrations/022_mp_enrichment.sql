-- Migration 022: MP enrichment — same bio/contact/social columns as senators
-- Run: psql $WTF_DATABASE_URL < 022_mp_enrichment.sql

ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS biography        TEXT;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS office_phone     TEXT;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS office_email     TEXT;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS twitter_handle   TEXT;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS linkedin_url     TEXT;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS website_url      TEXT;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS date_of_birth    DATE;
ALTER TABLE parliament.mps ADD COLUMN IF NOT EXISTS cabinet_role     TEXT;

-- MP committee memberships (House committees, separate from Senate committees)
CREATE TABLE IF NOT EXISTS parliament.mp_committees (
    id             SERIAL PRIMARY KEY,
    member_id      INTEGER NOT NULL REFERENCES parliament.mps(id) ON DELETE CASCADE,
    committee_abbr TEXT NOT NULL,
    committee_name TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'member', -- member, chair, vice_chair
    is_current     BOOLEAN DEFAULT true,
    UNIQUE(member_id, committee_abbr)
);
CREATE INDEX IF NOT EXISTS idx_mp_committees_member ON parliament.mp_committees(member_id);
CREATE INDEX IF NOT EXISTS idx_mp_committees_abbr   ON parliament.mp_committees(committee_abbr);
