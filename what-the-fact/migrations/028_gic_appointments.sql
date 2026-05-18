-- Migration 028: Governor in Council (GIC) appointments
-- Run: psql $WTF_DATABASE_URL < 028_gic_appointments.sql

CREATE SCHEMA IF NOT EXISTS gov_watch;

CREATE TABLE IF NOT EXISTS gov_watch.gic_appointments (
    id              SERIAL PRIMARY KEY,
    pc_number       TEXT UNIQUE NOT NULL,    -- e.g. "2026-0436"
    oic_date        DATE NOT NULL,           -- date OIC was made
    department      TEXT,                    -- dept abbreviation (JUS, PCH, ESDC...)
    subject         TEXT NOT NULL,           -- OIC subject line
    precis          TEXT,                    -- full appointment description
    oic_url         TEXT,                    -- link to OIC document
    appointee_name  TEXT,                    -- extracted name (optional)
    organization    TEXT,                    -- extracted org (optional)
    scraped_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gic_date   ON gov_watch.gic_appointments(oic_date DESC);
CREATE INDEX IF NOT EXISTS idx_gic_dept   ON gov_watch.gic_appointments(department);
