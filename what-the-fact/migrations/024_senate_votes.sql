-- Migration 024: Senate voting records
-- Run: psql $WTF_DATABASE_URL < 024_senate_votes.sql

CREATE TABLE IF NOT EXISTS parliament.senate_votes (
    id              SERIAL PRIMARY KEY,
    vote_id         TEXT UNIQUE NOT NULL,   -- sencanada.ca internal ID (e.g. "693986")
    session         TEXT NOT NULL,           -- e.g. "45-1"
    vote_number     INTEGER,                 -- sequential within session
    vote_date       DATE NOT NULL,
    title           TEXT NOT NULL,           -- vote description
    bill_number     TEXT,                    -- e.g. "C-24", "S-222"
    result          TEXT,                    -- "Adopted" or "Defeated"
    yea_total       INTEGER,
    nay_total       INTEGER,
    abstention_total INTEGER DEFAULT 0,
    absent_total    INTEGER DEFAULT 0,
    detail_url      TEXT,
    synced_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_senate_votes_date    ON parliament.senate_votes(vote_date DESC);
CREATE INDEX IF NOT EXISTS idx_senate_votes_session ON parliament.senate_votes(session);
CREATE INDEX IF NOT EXISTS idx_senate_votes_bill    ON parliament.senate_votes(bill_number);

CREATE TABLE IF NOT EXISTS parliament.senator_votes (
    id          SERIAL PRIMARY KEY,
    senator_id  INTEGER NOT NULL REFERENCES parliament.senators(id) ON DELETE CASCADE,
    vote_id     INTEGER NOT NULL REFERENCES parliament.senate_votes(id) ON DELETE CASCADE,
    ballot      TEXT NOT NULL CHECK (ballot IN ('yea','nay','abstention','absent')),
    UNIQUE(senator_id, vote_id)
);
CREATE INDEX IF NOT EXISTS idx_senator_votes_senator ON parliament.senator_votes(senator_id);
CREATE INDEX IF NOT EXISTS idx_senator_votes_vote    ON parliament.senator_votes(vote_id);
