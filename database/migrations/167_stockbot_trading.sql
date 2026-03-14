-- Migration 167: StockBot paper trading + strategies + Alpaca
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS stock_paper_accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    balance NUMERIC NOT NULL DEFAULT 100000,
    starting_balance NUMERIC NOT NULL DEFAULT 100000,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock_strategies (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    rules JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_evaluated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stock_strategy_logs (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES stock_strategies(id) ON DELETE CASCADE,
    action_taken VARCHAR(30),
    details JSONB DEFAULT '{}',
    executed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_strategies_user ON stock_strategies(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_stock_strategy_logs_strat ON stock_strategy_logs(strategy_id, executed_at DESC);
