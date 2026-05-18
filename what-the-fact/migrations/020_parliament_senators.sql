-- Migration 020: Senate of Canada — senators table + views
-- Run: psql $WTF_DATABASE_URL < 020_parliament_senators.sql

CREATE TABLE IF NOT EXISTS parliament.senators (
    id              SERIAL PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    given_name      TEXT,
    family_name     TEXT,
    caucus          TEXT,          -- ISG, CSG, PSG, C, GRO, Non-affiliated
    province        TEXT,
    photo_url       TEXT,
    profile_url     TEXT,          -- sencanada.ca URL
    appointed_at    DATE,
    is_current      BOOLEAN DEFAULT true,
    synced_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_senators_caucus ON parliament.senators(caucus);
CREATE INDEX IF NOT EXISTS idx_senators_province ON parliament.senators(province);

-- Caucus seat counts view
CREATE OR REPLACE VIEW parliament.senate_caucus_summary AS
SELECT caucus, COUNT(*) AS senator_count, MAX(synced_at) AS last_synced
FROM parliament.senators
WHERE is_current = true
GROUP BY caucus;
