-- 002: Add 6-agent analysis columns + strategy/sentiment tables

ALTER TABLE analyses ADD COLUMN value_report TEXT;
ALTER TABLE analyses ADD COLUMN value_score REAL;
ALTER TABLE analyses ADD COLUMN pulse_report TEXT;
ALTER TABLE analyses ADD COLUMN pulse_score REAL;
ALTER TABLE analyses ADD COLUMN oracle_synthesis TEXT;
ALTER TABLE analyses ADD COLUMN oracle_confidence REAL;
ALTER TABLE analyses ADD COLUMN market_execution TEXT;
ALTER TABLE analyses ADD COLUMN suggested_position_size REAL;
ALTER TABLE analyses ADD COLUMN stop_loss REAL;
ALTER TABLE analyses ADD COLUMN target_price REAL;

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
