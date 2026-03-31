-- Kytran Market Watch — M.A.R.K.E.T. Database Schema

-- Risk metrics cache (VaR, correlations, beta, Kelly params)
CREATE TABLE IF NOT EXISTS risk_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_type TEXT NOT NULL,
    ticker TEXT,
    data JSON NOT NULL,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(metric_type, ticker)
);


CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    notes TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    opened_by TEXT DEFAULT 'manual',
    thesis_id INTEGER,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thesis_id) REFERENCES analyses(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    order_type TEXT DEFAULT 'market',
    executed_by TEXT DEFAULT 'manual',
    thesis_id INTEGER,
    alpaca_order_id TEXT,
    status TEXT DEFAULT 'filled' CHECK (status IN ('pending', 'filled', 'cancelled', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thesis_id) REFERENCES analyses(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('price_above', 'price_below', 'volume', 'agent')),
    threshold REAL,
    message TEXT,
    triggered INTEGER DEFAULT 0,
    triggered_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    cycle_id INTEGER,
    director_thesis TEXT,
    director_sentiment TEXT CHECK (director_sentiment IN ('bullish', 'bearish', 'neutral')),
    director_confidence REAL,
    quant_report TEXT,
    quant_score REAL,
    quant_indicators TEXT,
    risk_assessment TEXT,
    risk_approved INTEGER DEFAULT 0,
    risk_position_size REAL,
    risk_stop_loss REAL,
    recommendation TEXT CHECK (recommendation IN ('buy', 'sell', 'hold', 'skip')),
    executed INTEGER DEFAULT 0,
    value_report TEXT,
    value_score REAL,
    pulse_report TEXT,
    pulse_score REAL,
    oracle_synthesis TEXT,
    oracle_confidence REAL,
    market_execution TEXT,
    suggested_position_size REAL,
    stop_loss REAL,
    target_price REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cycle_id) REFERENCES cycle_log(id)
);

CREATE TABLE IF NOT EXISTS market_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type IN ('quote', 'history', 'fundamentals', 'news')),
    data TEXT NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(ticker, data_type)
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    tickers TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_value REAL,
    total_return REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    win_rate REAL,
    trade_count INTEGER,
    equity_curve TEXT,
    trade_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    stocks_analyzed INTEGER DEFAULT 0,
    trades_made INTEGER DEFAULT 0,
    trades_skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'breaker_tripped')),
    details TEXT
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failure')),
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cash_balance REAL NOT NULL DEFAULT 100000.0,
    initial_balance REAL NOT NULL DEFAULT 100000.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed paper account if empty
INSERT OR IGNORE INTO paper_account (id, cash_balance, initial_balance) VALUES (1, 100000.0, 100000.0);

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    rules TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    backtest_count INTEGER DEFAULT 0,
    last_backtest_id INTEGER,
    win_rate REAL,
    total_return REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    headline TEXT,
    score REAL NOT NULL,
    summary TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sentiment_ticker ON sentiment_scores(ticker, created_at);

CREATE TABLE IF NOT EXISTS agent_dispatch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER REFERENCES analyses(id),
    agent_name TEXT NOT NULL,
    agent_id INTEGER,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    status TEXT DEFAULT 'success',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Local user cache (populated on OAuth login)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kytran_sub TEXT NOT NULL UNIQUE,
    username TEXT,
    email TEXT,
    name TEXT,
    role TEXT DEFAULT 'user',
    tier TEXT DEFAULT 'viewer',
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Open positions tracked by autonomous trading loop
CREATE TABLE IF NOT EXISTS open_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target_price REAL NOT NULL,
    max_hold_days INTEGER DEFAULT 5,
    sector TEXT,
    thesis_id INTEGER REFERENCES analyses(id),
    alpaca_order_id TEXT,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'stopped', 'target_hit', 'expired', 'reeval'))
);

-- Trade journal — every entry/exit with reasoning
CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    position_id INTEGER REFERENCES open_positions(id),
    thesis_id INTEGER REFERENCES analyses(id),
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    risk_gates_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolio lifetime metrics (single row)
CREATE TABLE IF NOT EXISTS portfolio_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peak_value REAL NOT NULL DEFAULT 100000.0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed portfolio metrics if empty
INSERT OR IGNORE INTO portfolio_metrics (id, peak_value) VALUES (1, 100000.0);

-- Trading configuration (single row, DB overrides env var defaults)
CREATE TABLE IF NOT EXISTS trading_config (
    id INTEGER PRIMARY KEY,
    config JSON NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO trading_config (id, config) VALUES (1, '{}');

-- News cache — headlines from multiple sources with sentiment scores
CREATE TABLE IF NOT EXISTS news_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('yfinance', 'alphavantage', 'manual')),
    headline TEXT NOT NULL,
    url TEXT,
    published_at TIMESTAMP,
    vader_score REAL,
    vader_sentiment TEXT CHECK (vader_sentiment IN ('positive', 'negative', 'neutral')),
    pulse_score REAL,
    pulse_summary TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, headline)
);
CREATE INDEX IF NOT EXISTS idx_news_cache_ticker ON news_cache(ticker, fetched_at DESC);

-- Monte Carlo simulation results
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

-- Walk-forward analysis results
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
