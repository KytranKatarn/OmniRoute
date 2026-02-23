-- 120_service_health_history.sql
-- Stores periodic health check snapshots for sparkline display in Dev HQ System tab

CREATE TABLE IF NOT EXISTS service_health_history (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    detail VARCHAR(255),
    response_time_ms INTEGER,
    checked_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_health_history_service ON service_health_history(service_name, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_history_time ON service_health_history(checked_at);
