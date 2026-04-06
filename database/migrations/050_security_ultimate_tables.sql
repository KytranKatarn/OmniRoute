-- Security Network Ultimate — 10 new tables
-- 2026-04-05

CREATE TABLE IF NOT EXISTS device_fingerprints (
    id SERIAL PRIMARY KEY,
    device_ip VARCHAR(45) NOT NULL,
    device_mac VARCHAR(17),
    os_name VARCHAR(255),
    os_version VARCHAR(100),
    open_ports JSONB DEFAULT '[]',
    services JSONB DEFAULT '[]',
    scanned_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(device_ip)
);

CREATE TABLE IF NOT EXISTS threat_intel_iocs (
    id SERIAL PRIMARY KEY,
    feed_name VARCHAR(100) NOT NULL,
    ioc_type VARCHAR(50) NOT NULL,
    ioc_value TEXT NOT NULL,
    severity VARCHAR(20) DEFAULT 'low',
    description TEXT,
    first_seen TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(feed_name, ioc_type, ioc_value)
);

CREATE TABLE IF NOT EXISTS threat_intel_hits (
    id SERIAL PRIMARY KEY,
    device_ip VARCHAR(45) NOT NULL,
    domain TEXT,
    ioc_id INTEGER REFERENCES threat_intel_iocs(id),
    detected_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_threat_intel_hits_device ON threat_intel_hits(device_ip);
CREATE INDEX IF NOT EXISTS idx_threat_intel_hits_detected ON threat_intel_hits(detected_at);

CREATE TABLE IF NOT EXISTS speed_test_results (
    id SERIAL PRIMARY KEY,
    download_mbps DECIMAL(10,2),
    upload_mbps DECIMAL(10,2),
    ping_ms DECIMAL(10,2),
    jitter_ms DECIMAL(10,2),
    server VARCHAR(255),
    tested_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS port_scan_history (
    id SERIAL PRIMARY KEY,
    device_ip VARCHAR(45) NOT NULL,
    port INTEGER NOT NULL,
    protocol VARCHAR(10) DEFAULT 'tcp',
    service VARCHAR(100),
    state VARCHAR(20),
    first_seen TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    UNIQUE(device_ip, port, protocol)
);

CREATE TABLE IF NOT EXISTS parental_schedules (
    id SERIAL PRIMARY KEY,
    device_mac VARCHAR(17),
    user_name VARCHAR(100),
    schedule JSONB DEFAULT '{}'::jsonb,
    blocked_categories TEXT[] DEFAULT '{}',
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_incidents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    severity VARCHAR(20) DEFAULT 'normal',
    device_ip VARCHAR(45),
    alert_ids INTEGER[] DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'open',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_security_incidents_status ON security_incidents(status);

CREATE TABLE IF NOT EXISTS honeypot_events (
    id SERIAL PRIMARY KEY,
    source_ip VARCHAR(45) NOT NULL,
    source_mac VARCHAR(17),
    dest_port INTEGER NOT NULL,
    protocol VARCHAR(10) DEFAULT 'tcp',
    payload_preview TEXT,
    detected_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pcap_captures (
    id SERIAL PRIMARY KEY,
    device_ip VARCHAR(45),
    file_path TEXT,
    duration_sec INTEGER,
    file_size BIGINT,
    status VARCHAR(20) DEFAULT 'running',
    started_at TIMESTAMP DEFAULT NOW(),
    stopped_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS traffic_categories (
    id SERIAL PRIMARY KEY,
    domain_pattern VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL,
    source VARCHAR(50) DEFAULT 'seed',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed traffic categories
INSERT INTO traffic_categories (domain_pattern, category, source) VALUES
    ('youtube.com', 'streaming', 'seed'),
    ('netflix.com', 'streaming', 'seed'),
    ('nflxvideo.net', 'streaming', 'seed'),
    ('disneyplus.com', 'streaming', 'seed'),
    ('hulu.com', 'streaming', 'seed'),
    ('twitch.tv', 'streaming', 'seed'),
    ('spotify.com', 'streaming', 'seed'),
    ('scdn.co', 'streaming', 'seed'),
    ('googlevideo.com', 'streaming', 'seed'),
    ('tiktok.com', 'social', 'seed'),
    ('tiktokcdn.com', 'social', 'seed'),
    ('facebook.com', 'social', 'seed'),
    ('fbcdn.net', 'social', 'seed'),
    ('instagram.com', 'social', 'seed'),
    ('snapchat.com', 'social', 'seed'),
    ('snap.com', 'social', 'seed'),
    ('twitter.com', 'social', 'seed'),
    ('x.com', 'social', 'seed'),
    ('reddit.com', 'social', 'seed'),
    ('discord.com', 'social', 'seed'),
    ('epicgames.com', 'gaming', 'seed'),
    ('roblox.com', 'gaming', 'seed'),
    ('steampowered.com', 'gaming', 'seed'),
    ('xbox.com', 'gaming', 'seed'),
    ('xboxlive.com', 'gaming', 'seed'),
    ('playstation.com', 'gaming', 'seed'),
    ('ea.com', 'gaming', 'seed'),
    ('minecraft.net', 'gaming', 'seed'),
    ('google.com', 'work', 'seed'),
    ('googleapis.com', 'work', 'seed'),
    ('microsoft.com', 'work', 'seed'),
    ('office.com', 'work', 'seed'),
    ('outlook.com', 'work', 'seed'),
    ('teams.microsoft.com', 'work', 'seed'),
    ('zoom.us', 'work', 'seed'),
    ('slack.com', 'work', 'seed'),
    ('github.com', 'work', 'seed'),
    ('cae.com', 'work', 'seed'),
    ('cae.ca', 'work', 'seed'),
    ('adobe.com', 'work', 'seed'),
    ('amazon.com', 'shopping', 'seed'),
    ('amazonaws.com', 'cloud', 'seed'),
    ('cloudflare.com', 'cloud', 'seed'),
    ('apple.com', 'cloud', 'seed'),
    ('icloud.com', 'cloud', 'seed'),
    ('akamai.net', 'cloud', 'seed')
ON CONFLICT (domain_pattern) DO NOTHING;
