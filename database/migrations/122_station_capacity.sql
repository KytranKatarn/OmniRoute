-- Migration 122: Station Capacity Schema (ADR-055)
-- Adds capacity limits to bridge_stations, event tracking table, and occupancy view

-- 1. ALTER bridge_stations — add capacity columns
ALTER TABLE bridge_stations
ADD COLUMN IF NOT EXISTS max_primary INTEGER DEFAULT 2,
ADD COLUMN IF NOT EXISTS max_auxiliary INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS allow_overflow BOOLEAN DEFAULT TRUE;

-- 2. CREATE station_capacity_events table
CREATE TABLE IF NOT EXISTS station_capacity_events (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL,
    agent_id INTEGER REFERENCES agents(id),
    agent_name VARCHAR(100),
    home_station_id INTEGER REFERENCES bridge_stations(id),
    job_id INTEGER,
    capability VARCHAR(50),
    slot_number INTEGER,
    reason TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sce_station_date ON station_capacity_events(station_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sce_agent ON station_capacity_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_sce_type ON station_capacity_events(event_type);

-- 3. CREATE convenience view for real-time slot occupancy
CREATE OR REPLACE VIEW v_station_slot_occupancy AS
SELECT
    bs.id AS station_id,
    bs.station_code,
    bs.station_name,
    bs.max_primary,
    bs.max_auxiliary,
    bs.allow_overflow,
    COUNT(CASE WHEN bj.metadata->>'is_cross_station' IS NULL
               OR bj.metadata->>'is_cross_station' = 'false'
               THEN 1 END) AS primary_occupied,
    COUNT(CASE WHEN bj.metadata->>'is_cross_station' = 'true'
               AND (bj.metadata->>'is_cloud' IS NULL
                    OR bj.metadata->>'is_cloud' = 'false')
               THEN 1 END) AS auxiliary_occupied,
    COUNT(CASE WHEN bj.metadata->>'is_cloud' = 'true' THEN 1 END) AS contractor_occupied
FROM bridge_stations bs
LEFT JOIN bridge_jobs bj ON bj.station_code = bs.station_code
    AND bj.status = 'running'
GROUP BY bs.id, bs.station_code, bs.station_name, bs.max_primary, bs.max_auxiliary, bs.allow_overflow;
