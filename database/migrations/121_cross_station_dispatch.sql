-- Migration 121: Cross-Station Dispatch Analytics
-- Adds GIN indexes for JSONB metadata queries and views for dispatch analytics

-- GIN index for JSONB metadata queries on task_execution_log
CREATE INDEX IF NOT EXISTS idx_tel_request_metadata_gin
    ON task_execution_log USING gin (request_metadata);

-- GIN index for bridge_jobs metadata
CREATE INDEX IF NOT EXISTS idx_bridge_jobs_metadata_gin
    ON bridge_jobs USING gin (metadata);

-- Materialized view: cross-station dispatch summary (refreshed on demand)
CREATE MATERIALIZED VIEW IF NOT EXISTS cross_station_dispatch_summary AS
SELECT
    request_metadata->>'home_station' AS home_station,
    request_metadata->>'dispatch_station' AS dispatch_station,
    capability,
    module_source,
    COUNT(*) AS dispatch_count,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
    ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100, 1) AS success_rate,
    MAX(created_at) AS last_dispatch
FROM task_execution_log
WHERE (request_metadata->>'is_cross_station')::boolean = true
GROUP BY home_station, dispatch_station, capability, module_source
ORDER BY dispatch_count DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_csds_unique
    ON cross_station_dispatch_summary
    (home_station, dispatch_station, capability, module_source);

-- View: station borrowing summary (live, 30-day window)
CREATE OR REPLACE VIEW station_borrowing_summary AS
SELECT
    bs_home.station_name AS home_station_name,
    bs_home.station_code AS home_station,
    bs_dispatch.station_name AS dispatch_station_name,
    bs_dispatch.station_code AS dispatch_station,
    COUNT(*) AS borrow_count,
    COUNT(DISTINCT tel.agent_name) AS agents_involved,
    MAX(tel.created_at) AS last_borrow
FROM task_execution_log tel
JOIN bridge_stations bs_home
    ON bs_home.station_code = tel.request_metadata->>'home_station'
JOIN bridge_stations bs_dispatch
    ON bs_dispatch.station_code = tel.request_metadata->>'dispatch_station'
WHERE (tel.request_metadata->>'is_cross_station')::boolean = true
  AND tel.created_at > NOW() - INTERVAL '30 days'
GROUP BY bs_home.station_name, bs_home.station_code, bs_dispatch.station_name, bs_dispatch.station_code
ORDER BY borrow_count DESC;
