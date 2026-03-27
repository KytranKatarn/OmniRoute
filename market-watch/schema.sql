-- Kytran Market Watch — M.A.R.K.E.T. Database Schema

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
