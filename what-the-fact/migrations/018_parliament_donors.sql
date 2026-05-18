-- Migration 018: Elections Canada political contribution data
-- Project #348 Phase 2: "Follow the money" — donor → party/riding → MP → vote → coverage
-- Source: https://www.elections.ca/fin/oda/od_cntrbtn_de_e.zip (updated quarterly)
-- Scope: 2019+ (43rd, 44th, 45th Parliament) ≈ 4.1M rows

CREATE TABLE IF NOT EXISTS parliament.ec_contributions (
    id              BIGSERIAL PRIMARY KEY,
    political_entity VARCHAR(100),          -- "Candidates", "Registered parties", "Registered associations"
    recipient_name  VARCHAR(500),           -- candidate / party / association name
    party           VARCHAR(200),           -- Political Party of Recipient
    electoral_district VARCHAR(200),        -- riding name — links to parliament.mps.riding_name
    electoral_event VARCHAR(200),           -- e.g. "45th general election"
    election_date   DATE,                   -- Fiscal/Election date
    form_id         VARCHAR(100),           -- EC form ID (not unique — one form, many rows)
    contributor_type VARCHAR(100),          -- "Individual", "Businesses" (pre-2007)
    contributor_name VARCHAR(500),          -- full name
    contributor_city VARCHAR(200),
    contributor_province CHAR(2),
    contributor_postal VARCHAR(10),
    contribution_date DATE,                 -- Contribution Received date
    monetary_amount DECIMAL(12,2),
    non_monetary_amount DECIMAL(12,2),
    synced_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_ec_party        ON parliament.ec_contributions (party);
CREATE INDEX IF NOT EXISTS ix_ec_district     ON parliament.ec_contributions (electoral_district);
CREATE INDEX IF NOT EXISTS ix_ec_province     ON parliament.ec_contributions (contributor_province);
CREATE INDEX IF NOT EXISTS ix_ec_date         ON parliament.ec_contributions (election_date DESC);
CREATE INDEX IF NOT EXISTS ix_ec_entity       ON parliament.ec_contributions (political_entity);
CREATE INDEX IF NOT EXISTS ix_ec_recipient    ON parliament.ec_contributions (recipient_name);
CREATE INDEX IF NOT EXISTS ix_ec_amount       ON parliament.ec_contributions (monetary_amount DESC);

-- Riding-level donor aggregation view — used on MP profile pages
-- Shows total donations to an MP's riding association per election cycle
CREATE OR REPLACE VIEW parliament.riding_donor_totals AS
SELECT
    electoral_district,
    party,
    electoral_event,
    COUNT(*)                    AS donation_count,
    SUM(monetary_amount)        AS total_donated,
    COUNT(DISTINCT contributor_name) AS unique_donors,
    MIN(monetary_amount)        AS min_donation,
    MAX(monetary_amount)        AS max_donation,
    AVG(monetary_amount)        AS avg_donation
FROM parliament.ec_contributions
WHERE political_entity IN ('Registered associations', 'Candidates')
  AND monetary_amount > 0
GROUP BY electoral_district, party, electoral_event;

-- Party donor aggregation view — for party-level analysis
CREATE OR REPLACE VIEW parliament.party_donor_totals AS
SELECT
    party,
    contributor_province,
    EXTRACT(YEAR FROM election_date)::int AS year,
    COUNT(*)                    AS donation_count,
    SUM(monetary_amount)        AS total_donated,
    COUNT(DISTINCT contributor_name) AS unique_donors
FROM parliament.ec_contributions
WHERE monetary_amount > 0
GROUP BY party, contributor_province, year;
