-- Migration 310: Family DNA profiles table
-- Stores uploaded DNA test results and ethnicity estimates

CREATE TABLE IF NOT EXISTS family_dna_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    provider VARCHAR(50) NOT NULL,
    snp_count INTEGER DEFAULT 0,
    ethnicity_estimates JSONB DEFAULT '{}',
    upload_filename VARCHAR(255),
    uploaded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_dna_user ON family_dna_profiles(user_id);
