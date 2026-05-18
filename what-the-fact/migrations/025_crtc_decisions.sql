-- Migration 025: CRTC decisions table
-- Stores Canadian Radio-television and Telecommunications Commission rulings
-- Run: psql $WTF_DATABASE_URL < 025_crtc_decisions.sql

CREATE SCHEMA IF NOT EXISTS legal_watch;

CREATE TABLE IF NOT EXISTS legal_watch.crtc_decisions (
    id              SERIAL PRIMARY KEY,
    decision_number TEXT UNIQUE NOT NULL,  -- e.g. "2026-90"
    decision_year   INTEGER NOT NULL,
    subject         TEXT,                  -- applicant/subject (e.g. "CBC", "Rogers")
    scope           TEXT,                  -- geographic scope ("Across Canada", "Toronto, Ontario")
    description     TEXT,                  -- full description text
    decision_type   TEXT,                  -- "broadcasting", "telecom", "compliance", "online_news"
    decision_url    TEXT,                  -- crtc.gc.ca URL
    wtf_source_slug TEXT,                  -- cross-link to wtf.sources.slug if outlet match
    scraped_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_crtc_year    ON legal_watch.crtc_decisions(decision_year DESC);
CREATE INDEX IF NOT EXISTS idx_crtc_subject ON legal_watch.crtc_decisions(subject);
CREATE INDEX IF NOT EXISTS idx_crtc_source  ON legal_watch.crtc_decisions(wtf_source_slug);
