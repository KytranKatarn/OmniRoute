-- Migration 168: StockBot sentiment + backtesting
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS stock_news_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    source VARCHAR(30) NOT NULL,
    headline TEXT NOT NULL,
    url TEXT,
    sentiment_score NUMERIC,
    published_at TIMESTAMP,
    analyzed_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock_backtest_results (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    strategy_name VARCHAR(100),
    ticker VARCHAR(10) NOT NULL,
    period VARCHAR(10) NOT NULL,
    initial_balance NUMERIC DEFAULT 100000,
    final_balance NUMERIC,
    metrics JSONB DEFAULT '{}',
    equity_curve JSONB DEFAULT '[]',
    trades JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_news_ticker ON stock_news_cache(ticker, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_backtest_user ON stock_backtest_results(user_id, created_at DESC);
