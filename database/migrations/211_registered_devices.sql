BEGIN;

CREATE TABLE IF NOT EXISTS registered_devices (
    id SERIAL PRIMARY KEY,
    device_name VARCHAR(100) NOT NULL,
    device_type VARCHAR(20) NOT NULL,
    hostname VARCHAR(200),
    hardware_info JSONB DEFAULT '{}',
    purpose TEXT DEFAULT '',
    api_key_hash VARCHAR(200),
    status VARCHAR(20) DEFAULT 'pending',
    user_id INTEGER,
    registered_at TIMESTAMP DEFAULT NOW(),
    approved_at TIMESTAMP,
    approved_by INTEGER,
    last_seen TIMESTAMP,
    request_count INTEGER DEFAULT 0,
    CONSTRAINT chk_device_type CHECK (device_type IN ('cli', 'node', 'kso', 'kbs', 'standalone')),
    CONSTRAINT chk_device_status CHECK (status IN ('pending', 'approved', 'denied', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_registered_devices_status ON registered_devices (status);
CREATE INDEX IF NOT EXISTS idx_registered_devices_type ON registered_devices (device_type);
CREATE INDEX IF NOT EXISTS idx_registered_devices_api_key ON registered_devices (api_key_hash);

COMMIT;
