CREATE TABLE IF NOT EXISTS legal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    source_url TEXT,
    source_name TEXT,
    category TEXT,
    jurisdiction TEXT DEFAULT 'Canada',
    published_date TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    raw_id TEXT,
    metadata TEXT,
    UNIQUE(raw_id, source_name)
);

CREATE TABLE IF NOT EXISTS regulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    gazette_part TEXT,
    reg_type TEXT,
    department TEXT,
    description TEXT,
    source_url TEXT,
    published_date TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(title, published_date)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    records_fetched INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_legal_events_type ON legal_events(event_type);
CREATE INDEX IF NOT EXISTS idx_legal_events_date ON legal_events(published_date);
CREATE INDEX IF NOT EXISTS idx_regulations_date ON regulations(published_date);
CREATE INDEX IF NOT EXISTS idx_regulations_type ON regulations(reg_type);
