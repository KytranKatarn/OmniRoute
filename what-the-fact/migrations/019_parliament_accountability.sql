-- Migration 019: Parliamentary Accountability Layer — expenses, lobbying, disclosures, promises
-- Run as wtfuser on wtf database: psql $WTF_DATABASE_URL < 019_parliament_accountability.sql

-- MP expense reports (quarterly totals from Our Commons)
CREATE TABLE IF NOT EXISTS parliament.mp_expenses (
    id              SERIAL PRIMARY KEY,
    mp_id           INTEGER REFERENCES parliament.mps(id) ON DELETE CASCADE,
    period          TEXT NOT NULL,             -- "2024-Q1"
    travel_cad      NUMERIC(12,2),
    hospitality_cad NUMERIC(12,2),
    contracts_cad   NUMERIC(12,2),
    salaries_cad    NUMERIC(12,2),
    total_cad       NUMERIC(12,2),
    source_url      TEXT,
    synced_at       TIMESTAMP DEFAULT NOW(),
    UNIQUE(mp_id, period)
);
CREATE INDEX IF NOT EXISTS idx_mp_expenses_mp_id ON parliament.mp_expenses(mp_id);

-- Lobbyist contacts — who contacted this MP
CREATE TABLE IF NOT EXISTS parliament.lobbyist_contacts (
    id                  SERIAL PRIMARY KEY,
    mp_id               INTEGER REFERENCES parliament.mps(id) ON DELETE CASCADE,
    comlog_id           TEXT,
    lobbyist_last       TEXT,
    lobbyist_first      TEXT,
    client_org          TEXT,
    communication_date  DATE,
    subject_matter      TEXT,
    synced_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE(comlog_id, mp_id)
);
CREATE INDEX IF NOT EXISTS idx_lobbyist_mp_id ON parliament.lobbyist_contacts(mp_id);
CREATE INDEX IF NOT EXISTS idx_lobbyist_date ON parliament.lobbyist_contacts(communication_date);

-- Ethics Commissioner disclosure links (no PDF parsing — link-only v1)
CREATE TABLE IF NOT EXISTS parliament.mp_disclosures (
    id               SERIAL PRIMARY KEY,
    mp_id            INTEGER REFERENCES parliament.mps(id) ON DELETE CASCADE,
    disclosure_year  INTEGER,
    disclosure_type  TEXT DEFAULT 'public',    -- public, initial, annual
    disclosure_url   TEXT,
    synced_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE(mp_id, disclosure_year, disclosure_type)
);
CREATE INDEX IF NOT EXISTS idx_mp_disclosures_mp_id ON parliament.mp_disclosures(mp_id);

-- Promise Tracker — campaign promises extracted from news articles
CREATE TABLE IF NOT EXISTS parliament.mp_promises (
    id             SERIAL PRIMARY KEY,
    mp_id          INTEGER REFERENCES parliament.mps(id) ON DELETE CASCADE,
    article_id     INTEGER,                    -- references wtf.articles(id)
    promise_text   TEXT NOT NULL,
    source_url     TEXT,
    published_at   TIMESTAMP,
    status         TEXT DEFAULT 'unverified',  -- unverified, kept, broken, partial
    extracted_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE(mp_id, article_id, promise_text)
);
CREATE INDEX IF NOT EXISTS idx_mp_promises_mp_id ON parliament.mp_promises(mp_id);
CREATE INDEX IF NOT EXISTS idx_mp_promises_status ON parliament.mp_promises(status);

-- Lobbying summary view
CREATE OR REPLACE VIEW parliament.mp_lobbying_summary AS
SELECT
    mp_id,
    COUNT(*)                                  AS total_contacts,
    COUNT(DISTINCT client_org)                AS unique_orgs,
    MAX(communication_date)                   AS last_contact,
    MIN(communication_date)                   AS first_contact
FROM parliament.lobbyist_contacts
GROUP BY mp_id;

-- Expense summary view
CREATE OR REPLACE VIEW parliament.mp_expense_summary AS
SELECT
    mp_id,
    SUM(travel_cad)      AS total_travel,
    SUM(hospitality_cad) AS total_hospitality,
    SUM(contracts_cad)   AS total_contracts,
    SUM(total_cad)       AS grand_total,
    COUNT(*)             AS periods_reported
FROM parliament.mp_expenses
GROUP BY mp_id;
