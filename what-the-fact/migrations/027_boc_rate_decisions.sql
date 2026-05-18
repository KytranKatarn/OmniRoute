-- Migration 027: Bank of Canada rate decisions
-- Run: psql $WTF_DATABASE_URL < 027_boc_rate_decisions.sql

CREATE SCHEMA IF NOT EXISTS market_watch;

CREATE TABLE IF NOT EXISTS market_watch.boc_rate_decisions (
    id              SERIAL PRIMARY KEY,
    decision_date   DATE UNIQUE NOT NULL,
    rate_pct        DECIMAL(5,3) NOT NULL,   -- e.g. 2.750
    change_bps      INTEGER,                 -- NULL=first, 0=hold, neg=cut, pos=hike
    press_release_url TEXT,
    scraped_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_boc_rate_date ON market_watch.boc_rate_decisions(decision_date DESC);
