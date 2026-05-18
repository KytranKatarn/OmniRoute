-- Migration 021: Senate enrichment — bio, contact, committees, DOB, appointing PM
-- Run: psql $WTF_DATABASE_URL < 021_senate_enrichment.sql

ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS date_of_birth   DATE;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS appointed_by     TEXT;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS biography        TEXT;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS office_phone     TEXT;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS office_email     TEXT;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS twitter_handle   TEXT;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS linkedin_url     TEXT;
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS website_url      TEXT;

CREATE TABLE IF NOT EXISTS parliament.senator_committees (
    id            SERIAL PRIMARY KEY,
    senator_id    INTEGER NOT NULL REFERENCES parliament.senators(id) ON DELETE CASCADE,
    committee_abbr TEXT NOT NULL,
    committee_name TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member', -- member, chair, deputy_chair
    is_current    BOOLEAN DEFAULT true,
    UNIQUE(senator_id, committee_abbr)
);
CREATE INDEX IF NOT EXISTS idx_sen_committees_senator ON parliament.senator_committees(senator_id);
CREATE INDEX IF NOT EXISTS idx_sen_committees_abbr    ON parliament.senator_committees(committee_abbr);
