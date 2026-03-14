-- Migration 164: StockBot Foundation
-- 6 tables: watchlist, portfolio, transactions, price cache, history cache, alerts
-- Created: 2026-03-14

-- Stock Watchlist
CREATE TABLE IF NOT EXISTS stock_watchlist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT,
    alert_above NUMERIC(12, 4),
    alert_below NUMERIC(12, 4),
    UNIQUE (user_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_stock_watchlist_user_id ON stock_watchlist (user_id);
CREATE INDEX IF NOT EXISTS idx_stock_watchlist_ticker ON stock_watchlist (ticker);

-- Stock Portfolio
CREATE TABLE IF NOT EXISTS stock_portfolio (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    shares NUMERIC(18, 6) NOT NULL DEFAULT 0,
    avg_cost NUMERIC(12, 4) NOT NULL DEFAULT 0,
    current_price NUMERIC(12, 4),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_stock_portfolio_user_id ON stock_portfolio (user_id);
CREATE INDEX IF NOT EXISTS idx_stock_portfolio_ticker ON stock_portfolio (ticker);

-- Stock Transactions
CREATE TABLE IF NOT EXISTS stock_transactions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK (action IN ('buy', 'sell')),
    shares NUMERIC(18, 6) NOT NULL,
    price NUMERIC(12, 4) NOT NULL,
    total NUMERIC(18, 4) NOT NULL,
    paper_trade BOOLEAN NOT NULL DEFAULT TRUE,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_transactions_user_id ON stock_transactions (user_id);
CREATE INDEX IF NOT EXISTS idx_stock_transactions_ticker ON stock_transactions (ticker);
CREATE INDEX IF NOT EXISTS idx_stock_transactions_executed_at ON stock_transactions (executed_at DESC);

-- Stock Price Cache
CREATE TABLE IF NOT EXISTS stock_price_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    price NUMERIC(12, 4),
    change_pct NUMERIC(8, 4),
    volume BIGINT,
    market_cap BIGINT,
    pe_ratio NUMERIC(10, 4),
    dividend_yield NUMERIC(8, 4),
    high_52w NUMERIC(12, 4),
    low_52w NUMERIC(12, 4),
    data JSONB,
    cached_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_price_cache_cached_at ON stock_price_cache (cached_at);

-- Stock History Cache
CREATE TABLE IF NOT EXISTS stock_history_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    period VARCHAR(10) NOT NULL,
    ohlcv JSONB,
    cached_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker, period)
);

CREATE INDEX IF NOT EXISTS idx_stock_history_cache_ticker ON stock_history_cache (ticker);

-- Stock Alerts
CREATE TABLE IF NOT EXISTS stock_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    condition VARCHAR(20) NOT NULL CHECK (condition IN ('above', 'below', 'change_pct_up', 'change_pct_down')),
    threshold NUMERIC(12, 4) NOT NULL,
    triggered BOOLEAN NOT NULL DEFAULT FALSE,
    triggered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_alerts_user_id ON stock_alerts (user_id);
CREATE INDEX IF NOT EXISTS idx_stock_alerts_ticker ON stock_alerts (ticker);
CREATE INDEX IF NOT EXISTS idx_stock_alerts_triggered ON stock_alerts (triggered) WHERE triggered = FALSE;
