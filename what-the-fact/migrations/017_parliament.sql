-- Migration 017: Parliamentary Accountability Layer — MP Votes, Donors & Disclosures
-- Project #348 Phase 1: MPs + votes via OpenParliament.ca API
-- Elections Canada donor data added in Phase 2 (018_parliament_donors.sql)

CREATE SCHEMA IF NOT EXISTS parliament;

-- ── Members of Parliament ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parliament.mps (
    id               SERIAL PRIMARY KEY,
    slug             VARCHAR(200) NOT NULL UNIQUE,  -- OpenParliament URL slug
    name             VARCHAR(200) NOT NULL,
    given_name       VARCHAR(100),
    family_name      VARCHAR(100),
    party            VARCHAR(100),
    riding_name      VARCHAR(200),
    province_code    CHAR(2),
    photo_url        TEXT,
    twitter          VARCHAR(100),
    email            VARCHAR(200),
    parl_mp_id       VARCHAR(50),
    is_current       BOOLEAN NOT NULL DEFAULT true,
    openparl_url     VARCHAR(500),
    fetched_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_mps_party     ON parliament.mps (party);
CREATE INDEX IF NOT EXISTS ix_mps_province  ON parliament.mps (province_code);
CREATE INDEX IF NOT EXISTS ix_mps_current   ON parliament.mps (is_current);

-- ── Bills / Vote Motions ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parliament.bills (
    id              SERIAL PRIMARY KEY,
    session         VARCHAR(10) NOT NULL,    -- e.g. "45-1"
    vote_number     INTEGER NOT NULL,
    bill_number     VARCHAR(50),             -- e.g. "C-47" (nullable — not all votes are on bills)
    description_en  TEXT,
    description_fr  TEXT,
    vote_date       DATE,
    result          VARCHAR(50),             -- "Passed" | "Failed"
    yea_total       INTEGER,
    nay_total       INTEGER,
    paired_total    INTEGER,
    openparl_url    VARCHAR(500),
    fetched_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (session, vote_number)
);

CREATE INDEX IF NOT EXISTS ix_bills_session   ON parliament.bills (session);
CREATE INDEX IF NOT EXISTS ix_bills_date      ON parliament.bills (vote_date DESC);
CREATE INDEX IF NOT EXISTS ix_bills_number    ON parliament.bills (bill_number);

-- ── Per-MP Ballot Records ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parliament.mp_votes (
    id         SERIAL PRIMARY KEY,
    mp_id      INTEGER NOT NULL REFERENCES parliament.mps(id)   ON DELETE CASCADE,
    bill_id    INTEGER NOT NULL REFERENCES parliament.bills(id)  ON DELETE CASCADE,
    ballot     VARCHAR(10) NOT NULL CHECK (ballot IN ('Yes', 'No', 'Paired', 'Absent')),
    fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (mp_id, bill_id)
);

CREATE INDEX IF NOT EXISTS ix_mp_votes_mp    ON parliament.mp_votes (mp_id);
CREATE INDEX IF NOT EXISTS ix_mp_votes_bill  ON parliament.mp_votes (bill_id);
CREATE INDEX IF NOT EXISTS ix_mp_votes_ballot ON parliament.mp_votes (ballot);

-- ── Article ↔ MP Tag Table ───────────────────────────────────────────────────
-- Links WTF articles to MPs mentioned in the text.
-- Populated by the article tagging pass (NER or name-match against parliament.mps).
CREATE TABLE IF NOT EXISTS wtf.article_mp_tags (
    id          SERIAL PRIMARY KEY,
    article_id  INTEGER NOT NULL REFERENCES wtf.articles(id)  ON DELETE CASCADE,
    mp_id       INTEGER NOT NULL REFERENCES parliament.mps(id) ON DELETE CASCADE,
    match_type  VARCHAR(20) NOT NULL DEFAULT 'name_match'
                CHECK (match_type IN ('name_match', 'slug_match', 'llm')),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (article_id, mp_id)
);

CREATE INDEX IF NOT EXISTS ix_article_mp_article ON wtf.article_mp_tags (article_id);
CREATE INDEX IF NOT EXISTS ix_article_mp_mp      ON wtf.article_mp_tags (mp_id);

-- ── Ingest tracking ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parliament.ingest_log (
    id          SERIAL PRIMARY KEY,
    run_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    task        VARCHAR(100) NOT NULL,
    records_fetched  INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    error       TEXT
);
