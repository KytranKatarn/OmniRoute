-- Migration 060: Security Network NOC Tables
-- Tables: network_device_users, network_traffic_stats, network_dns_stats,
--         network_daily_reports, network_ip_history, network_alerts, nagios_check_results

BEGIN;

-- 1. Device-to-user mapping (MAC → person)
CREATE TABLE IF NOT EXISTS network_device_users (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(17) UNIQUE NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    device_label VARCHAR(200),
    device_type VARCHAR(50) DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Hourly bandwidth aggregates from ntopng
CREATE TABLE IF NOT EXISTS network_traffic_stats (
    id SERIAL PRIMARY KEY,
    device_mac VARCHAR(17),
    device_ip VARCHAR(45),
    bytes_in BIGINT DEFAULT 0,
    bytes_out BIGINT DEFAULT 0,
    protocol VARCHAR(50),
    hour_bucket TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traffic_stats_hour ON network_traffic_stats (hour_bucket);
CREATE INDEX IF NOT EXISTS idx_traffic_stats_device ON network_traffic_stats (device_mac);

-- 3. Hourly DNS query aggregates from AdGuard
CREATE TABLE IF NOT EXISTS network_dns_stats (
    id SERIAL PRIMARY KEY,
    client_ip VARCHAR(45),
    total_queries INTEGER DEFAULT 0,
    blocked_queries INTEGER DEFAULT 0,
    top_domains JSONB DEFAULT '[]',
    hour_bucket TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dns_stats_hour ON network_dns_stats (hour_bucket);
CREATE INDEX IF NOT EXISTS idx_dns_stats_client ON network_dns_stats (client_ip);

-- 4. Generated reports
CREATE TABLE IF NOT EXISTS network_daily_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    report_type VARCHAR(50) NOT NULL,
    data_json JSONB NOT NULL,
    pdf_path VARCHAR(500),
    delivered_via JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 5. DDNS IP change log
CREATE TABLE IF NOT EXISTS network_ip_history (
    id SERIAL PRIMARY KEY,
    old_ip VARCHAR(45),
    new_ip VARCHAR(45) NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    dns_updated BOOLEAN DEFAULT FALSE,
    subdomains_updated JSONB DEFAULT '[]'
);

-- 6. NOC alerts
CREATE TABLE IF NOT EXISTS network_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    source VARCHAR(50) NOT NULL,
    title VARCHAR(300) NOT NULL,
    details JSONB DEFAULT '{}',
    auto_action_taken VARCHAR(200),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_severity ON network_alerts (severity);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON network_alerts (created_at);

-- 7. Cached Nagios check results
CREATE TABLE IF NOT EXISTS nagios_check_results (
    id SERIAL PRIMARY KEY,
    host_name VARCHAR(200) NOT NULL,
    service_description VARCHAR(200) DEFAULT '',
    status VARCHAR(20) NOT NULL,
    output TEXT,
    performance_data TEXT,
    last_check TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nagios_host_service
    ON nagios_check_results (host_name, COALESCE(service_description, ''));

COMMIT;
