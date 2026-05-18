-- Migration 026: Ethics Commissioner rulings
-- Run: psql $WTF_DATABASE_URL < 026_ethics_rulings.sql

CREATE TABLE IF NOT EXISTS legal_watch.ethics_rulings (
    id              SERIAL PRIMARY KEY,
    report_name     TEXT UNIQUE NOT NULL,    -- e.g. "Fox Report"
    subject_name    TEXT,                    -- e.g. "Fox", "Trudeau"
    ruling_date     DATE,
    report_type     TEXT,                    -- "act" or "code"
    finding         TEXT,                    -- summary / finding if known
    report_url      TEXT,
    mp_slug         TEXT,                    -- cross-link to parliament.mps.slug
    senator_slug    TEXT,                    -- cross-link to parliament.senators.slug
    scraped_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ethics_date    ON legal_watch.ethics_rulings(ruling_date DESC);
CREATE INDEX IF NOT EXISTS idx_ethics_mp      ON legal_watch.ethics_rulings(mp_slug);
CREATE INDEX IF NOT EXISTS idx_ethics_senator ON legal_watch.ethics_rulings(senator_slug);
