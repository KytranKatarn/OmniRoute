-- Migration 107: Move ingest bootstrap DDL to operator migrations.
-- Idempotent: safe to run multiple times. Apply to the dedicated Citadel WTF DB.
-- Run before deploying the restricted-runtime ingest code; no runtime grants here.

CREATE SCHEMA IF NOT EXISTS gov_watch;

CREATE TABLE IF NOT EXISTS gov_watch.gic_appointments (
    id              SERIAL PRIMARY KEY,
    pc_number       TEXT UNIQUE NOT NULL,
    oic_date        DATE NOT NULL,
    department      TEXT,
    subject         TEXT NOT NULL,
    precis          TEXT,
    oic_url         TEXT,
    appointee_name  TEXT,
    organization    TEXT,
    action_type     TEXT NOT NULL DEFAULT 'appointment',
    scraped_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gic_date ON gov_watch.gic_appointments(oic_date DESC);

ALTER TABLE gov_watch.gic_appointments ADD COLUMN IF NOT EXISTS action_type TEXT NOT NULL DEFAULT 'appointment';

CREATE SCHEMA IF NOT EXISTS securities;
CREATE TABLE IF NOT EXISTS securities.issuers (
    ticker            text PRIMARY KEY,
    name              text NOT NULL,
    exchange          text NOT NULL DEFAULT 'TSX',
    index_membership  text,
    source            text NOT NULL DEFAULT 'wikipedia',
    fetched_at        timestamptz NOT NULL DEFAULT now()
);

CREATE SCHEMA IF NOT EXISTS market_watch;

CREATE TABLE IF NOT EXISTS market_watch.boc_rate_decisions (
    id              SERIAL PRIMARY KEY,
    decision_date   DATE UNIQUE NOT NULL,
    rate_pct        DECIMAL(5,3) NOT NULL,
    change_bps      INTEGER,
    press_release_url TEXT,
    scraped_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_boc_rate_date ON market_watch.boc_rate_decisions(decision_date DESC);

CREATE TABLE IF NOT EXISTS market_watch.economic_indicators (
    id            SERIAL PRIMARY KEY,
    indicator_key TEXT NOT NULL,
    ref_date      DATE NOT NULL,
    value         DECIMAL(14,4) NOT NULL,
    vector_id     INTEGER NOT NULL,
    table_id      TEXT NOT NULL,
    release_time  TIMESTAMPTZ,
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (indicator_key, ref_date)
);

CREATE INDEX IF NOT EXISTS idx_economic_indicators_key_date ON market_watch.economic_indicators(indicator_key, ref_date DESC);

CREATE TABLE IF NOT EXISTS market_watch.fiscal_federal_annual (
    ref_year       INTEGER NOT NULL,
    item_key       TEXT NOT NULL,
    value_millions NUMERIC(16,1) NOT NULL,
    vector_id      BIGINT NOT NULL,
    source_table   TEXT NOT NULL,
    derived        BOOLEAN NOT NULL DEFAULT FALSE,
    release_time   TIMESTAMPTZ,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ref_year, item_key)
);

CREATE TABLE IF NOT EXISTS market_watch.fiscal_federal_quarterly (
    ref_quarter    DATE NOT NULL,
    item_key       TEXT NOT NULL,
    value_millions NUMERIC(16,1) NOT NULL,
    vector_id      BIGINT NOT NULL,
    source_table   TEXT NOT NULL,
    release_time   TIMESTAMPTZ,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ref_quarter, item_key)
);

CREATE TABLE IF NOT EXISTS market_watch.fx_rates (
    id         SERIAL PRIMARY KEY,
    rate_date  DATE UNIQUE NOT NULL,
    usd_cad    DECIMAL(8,4) NOT NULL,
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fx_rates_date ON market_watch.fx_rates(rate_date DESC);

CREATE TABLE IF NOT EXISTS market_watch.oda_canada_annual (
    ref_year   INTEGER NOT NULL,
    item_key   TEXT NOT NULL,
    value      NUMERIC(14,3) NOT NULL,
    unit       TEXT NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ref_year, item_key)
);

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('107', '107_ingest_schema_bootstrap.sql',
        'Operator-owned GIC, securities and market ingest schema bootstrap', now())
ON CONFLICT (version) DO NOTHING;
