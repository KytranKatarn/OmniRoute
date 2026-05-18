-- Migration 023: Officers of Parliament registry
-- Independent accountability watchdogs who report directly to Parliament
-- Run: psql $WTF_DATABASE_URL < 023_officers_of_parliament.sql

CREATE TABLE IF NOT EXISTS parliament.officers (
    id              SERIAL PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,              -- e.g. "Auditor General of Canada"
    short_title     TEXT NOT NULL,              -- e.g. "Auditor General"
    current_holder  TEXT,                       -- name of current officer
    appointed_at    DATE,
    mandate_summary TEXT,                       -- 1-2 sentence mandate description
    website_url     TEXT,
    report_url      TEXT,                       -- latest annual/special report URL
    report_title    TEXT,                       -- latest report title
    report_date     DATE,
    cross_links     TEXT[],                     -- which Watch products this connects to
    is_active       BOOLEAN DEFAULT true,
    synced_at       TIMESTAMP DEFAULT NOW()
);

-- Seed: 7 Officers of Parliament + Senate Ethics Officer
INSERT INTO parliament.officers
    (slug, title, short_title, current_holder, appointed_at, mandate_summary, website_url, cross_links)
VALUES
(
    'auditor-general',
    'Auditor General of Canada',
    'Auditor General',
    'Karen Hogan',
    '2020-06-09',
    'Audits federal government programs and operations to assess whether public money is being spent wisely and reports findings to Parliament. AG reports are among the most consequential accountability documents in Canada.',
    'https://www.oag-bvg.gc.ca',
    ARRAY['gov-watch', 'civic-watch']
),
(
    'parliamentary-budget-officer',
    'Parliamentary Budget Officer',
    'Budget Officer',
    'Yves Giroux',
    '2018-09-01',
    'Provides independent analysis of the state of Canada''s finances and the government''s estimates. Costs government bills and produces economic and fiscal projections.',
    'https://www.pbo-dpb.ca',
    ARRAY['market-watch', 'civic-watch']
),
(
    'ethics-commissioner',
    'Conflict of Interest and Ethics Commissioner',
    'Ethics Commissioner',
    'Konrad von Finckenstein',
    '2023-12-12',
    'Administers the Conflict of Interest Act for ministers, parliamentary secretaries, and senior public servants. Investigates complaints and issues public reports on ethics violations.',
    'https://ciec-ccie.gc.ca',
    ARRAY['wtf', 'civic-watch']
),
(
    'commissioner-of-lobbying',
    'Commissioner of Lobbying',
    'Lobbying Commissioner',
    'Nancy Bélanger',
    '2018-01-01',
    'Maintains the Registry of Lobbyists and enforces the Lobbying Act. Investigates complaints about lobbying activities and ensures transparency of communication between lobbyists and public office holders.',
    'https://lobbycanada.gc.ca',
    ARRAY['civic-watch', 'wtf']
),
(
    'chief-electoral-officer',
    'Chief Electoral Officer of Canada',
    'Chief Electoral Officer',
    'Stéphane Perrault',
    '2018-05-28',
    'Administers federal elections and referendums, registers political parties and candidates, and oversees campaign finance compliance through Elections Canada.',
    'https://www.elections.ca',
    ARRAY['wtf', 'civic-watch']
),
(
    'privacy-commissioner',
    'Privacy Commissioner of Canada',
    'Privacy Commissioner',
    'Philippe Dufresne',
    '2022-07-21',
    'Oversees compliance with the Privacy Act and PIPEDA. Investigates complaints, conducts audits, and reports publicly on privacy breaches by federal institutions and private-sector organizations.',
    'https://www.priv.gc.ca',
    ARRAY['civic-watch', 'legal-watch']
),
(
    'information-commissioner',
    'Information Commissioner of Canada',
    'Information Commissioner',
    'Caroline Maynard',
    '2018-03-01',
    'Investigates complaints from people who believe their access to information requests were wrongly denied or delayed by federal institutions. Promotes transparency and accountability in government.',
    'https://www.oic-ci.gc.ca',
    ARRAY['civic-watch']
),
(
    'senate-ethics-officer',
    'Senate Ethics Officer',
    'Senate Ethics Officer',
    'Kimberley Byers',
    '2022-07-01',
    'Provides confidential advice to senators on the Conflict of Interest Code for Senators and investigates alleged breaches. Reports to the Senate, not the House of Commons.',
    'https://www.seo-cse.gc.ca',
    ARRAY['wtf']
)
ON CONFLICT (slug) DO UPDATE SET
    current_holder  = EXCLUDED.current_holder,
    mandate_summary = EXCLUDED.mandate_summary,
    website_url     = EXCLUDED.website_url,
    cross_links     = EXCLUDED.cross_links,
    synced_at       = NOW();
