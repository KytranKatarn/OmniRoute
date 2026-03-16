-- 172_network_devices.sql
-- Network device registry for AdGuard integration
-- Source of truth for all devices on the network

CREATE TABLE IF NOT EXISTS network_devices (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(17),
    ip_address INET NOT NULL,
    hostname VARCHAR(255),
    friendly_name VARCHAR(255),
    device_type VARCHAR(50),
    owner VARCHAR(100),
    security_zone VARCHAR(20) DEFAULT 'quarantined'
        CHECK (security_zone IN ('trusted', 'family', 'guest', 'iot', 'quarantined')),
    manufacturer VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'decommissioned', 'banned')),
    adguard_client_id VARCHAR(100),
    is_registered BOOLEAN DEFAULT FALSE,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Unique constraints
CREATE UNIQUE INDEX IF NOT EXISTS idx_network_devices_ip ON network_devices (ip_address);
CREATE UNIQUE INDEX IF NOT EXISTS idx_network_devices_mac ON network_devices (mac_address) WHERE mac_address IS NOT NULL;

-- Query indexes
CREATE INDEX IF NOT EXISTS idx_network_devices_zone ON network_devices (security_zone);
CREATE INDEX IF NOT EXISTS idx_network_devices_registered ON network_devices (is_registered);
CREATE INDEX IF NOT EXISTS idx_network_devices_last_seen ON network_devices (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_network_devices_status ON network_devices (status);
