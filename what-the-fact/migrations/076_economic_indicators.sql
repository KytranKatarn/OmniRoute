-- 076_economic_indicators.sql — StatCan CPI/unemployment/GDP/housing-starts (Batch 12)
--
-- Feeds ingest/market/statcan_indicators.py, one row per (indicator, month).
-- Source: StatCan Web Data Service (WDS) REST API,
-- getDataFromVectorsAndLatestNPeriods — no auth required, verified live
-- 2026-09-04. Four indicators, four vectorIds:
--   cpi_index           vectorId 41690973  table 18-10-0004-01 (raw index, 2002=100)
--   unemployment_rate   vectorId 2062815   table 14-10-0287-01 (Labour Force Survey, %)
--   gdp_level           vectorId 65201210  table 36-10-0434-01 (real GDP, $M chained, monthly)
--   housing_starts_saar vectorId 52300157  table 34-10-0158-01 (CMHC housing starts, SAAR, thousands)
--
-- Every value is stored RAW as StatCan reports it — cpi_index and gdp_level
-- are NOT percentages, they are an index and a dollar level respectively.
-- Year-over-year / month-over-month derivations are computed in the route
-- layer, never here (mirrors market_watch.boc_rate_decisions storing raw
-- rate_pct and the /rates route deriving "since peak"/consecutive-holds).
--
-- Belt-and-suspenders: ingest/market/statcan_indicators.py's own _upsert()
-- also runs CREATE TABLE IF NOT EXISTS for this same schema (boc_rates.py's
-- pattern) — this migration and the ingest module must stay byte-identical
-- on the DDL.

CREATE SCHEMA IF NOT EXISTS market_watch;

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

CREATE INDEX IF NOT EXISTS idx_economic_indicators_key_date
    ON market_watch.economic_indicators(indicator_key, ref_date DESC);
