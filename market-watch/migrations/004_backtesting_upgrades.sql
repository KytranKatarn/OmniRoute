-- migrations/004_backtesting_upgrades.sql
-- Idempotent migration for Phase B6 backtesting upgrades

CREATE TABLE IF NOT EXISTS monte_carlo_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER,
    ticker TEXT NOT NULL,
    strategy TEXT NOT NULL,
    simulations INTEGER NOT NULL DEFAULT 1000,
    mean_return REAL,
    std_return REAL,
    percentile_5 REAL,
    percentile_25 REAL,
    percentile_50 REAL,
    percentile_75 REAL,
    percentile_95 REAL,
    ruin_probability REAL,
    mean_sharpe REAL,
    mean_max_drawdown REAL,
    data JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS walk_forward_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    tickers TEXT NOT NULL,
    window_size INTEGER NOT NULL DEFAULT 252,
    step_size INTEGER NOT NULL DEFAULT 63,
    windows JSON NOT NULL,
    avg_oos_sharpe REAL,
    consistency_ratio REAL,
    overfitting_score REAL,
    params_used JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
