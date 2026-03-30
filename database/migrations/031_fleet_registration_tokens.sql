-- 031_fleet_registration_tokens.sql
-- Fleet registration tokens + remote_nodes extensions

CREATE TABLE IF NOT EXISTS fleet_registration_tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) NOT NULL UNIQUE,
    node_type VARCHAR(20) NOT NULL CHECK (node_type IN ('outpost', 'starship', 'satellite')),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    used_by_node_id VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_fleet_tokens_token ON fleet_registration_tokens(token);
CREATE INDEX IF NOT EXISTS idx_fleet_tokens_expires ON fleet_registration_tokens(expires_at);

ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS registration_method VARCHAR(20) DEFAULT 'approval';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS device_info JSONB DEFAULT '{}';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS apps_running JSONB DEFAULT '[]';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS node_name VARCHAR(100);
