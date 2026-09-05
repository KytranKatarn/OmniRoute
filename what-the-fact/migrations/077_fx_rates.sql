-- Migration 077: CAD/USD daily exchange rate table (Batch 12, fx_rates ingest)
-- Mirrors the belt-and-suspenders CREATE TABLE IF NOT EXISTS in
-- ingest/market/fx_rates.py's _upsert() — this migration is the tracked
-- schema record; the ingest module's own guard keeps a fresh DB working
-- even if migrations haven't run yet (same pattern as boc_rates.py /
-- migration 076-adjacent boc_rate_decisions).

CREATE SCHEMA IF NOT EXISTS market_watch;

CREATE TABLE IF NOT EXISTS market_watch.fx_rates (
    id         SERIAL PRIMARY KEY,
    rate_date  DATE UNIQUE NOT NULL,
    usd_cad    DECIMAL(8,4) NOT NULL,
    scraped_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fx_rates_date ON market_watch.fx_rates(rate_date DESC);
