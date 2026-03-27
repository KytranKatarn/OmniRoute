CREATE TABLE IF NOT EXISTS civic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    level TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    amount REAL,
    department TEXT,
    vendor TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    source_url TEXT,
    source_name TEXT,
    raw_id TEXT,
    event_date TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    metadata TEXT,
    UNIQUE(raw_id, source_name)
);

CREATE TABLE IF NOT EXISTS parliament_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_number TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    sponsor TEXT,
    status TEXT,
    introduced_date TEXT,
    last_activity_date TEXT,
    session TEXT,
    source_url TEXT,
    UNIQUE(bill_number, session)
);

CREATE TABLE IF NOT EXISTS parliament_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vote_number INTEGER,
    bill_number TEXT,
    description TEXT,
    result TEXT,
    yeas INTEGER,
    nays INTEGER,
    paired INTEGER,
    vote_date TEXT NOT NULL,
    session TEXT,
    source_url TEXT
);

CREATE TABLE IF NOT EXISTS spending_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    department TEXT NOT NULL,
    category TEXT,
    amount REAL NOT NULL,
    fiscal_year TEXT,
    description TEXT,
    source_url TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE(department, fiscal_year, level)
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

CREATE INDEX IF NOT EXISTS idx_civic_events_type ON civic_events(event_type);
CREATE INDEX IF NOT EXISTS idx_civic_events_level ON civic_events(level);
CREATE INDEX IF NOT EXISTS idx_civic_events_jurisdiction ON civic_events(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_civic_events_date ON civic_events(event_date);
CREATE INDEX IF NOT EXISTS idx_spending_jurisdiction ON spending_records(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_bills_status ON parliament_bills(status);
CREATE INDEX IF NOT EXISTS idx_ingest_log_source ON ingest_log(source);
