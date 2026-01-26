-- Migration 023: Shift Scheduler System
-- Phase 28: Consciousness Optimization & Admin Ops Integration
-- Created: 2026-01-17
--
-- This migration adds full shift scheduling capabilities:
-- - Shift definitions (Morning, Afternoon, Night)
-- - Agent shift assignments with day-of-week granularity
-- - Rotation schedules for automatic shift cycling
-- - Conflict detection and tracking
-- - Views for on-duty agents and scheduling queries

-- =============================================================================
-- SHIFT DEFINITIONS TABLE
-- =============================================================================
-- Defines the available shifts with time ranges

CREATE TABLE IF NOT EXISTS shift_definitions (
    id SERIAL PRIMARY KEY,
    shift_name VARCHAR(50) NOT NULL UNIQUE,
    shift_code VARCHAR(10) NOT NULL UNIQUE,  -- 'AM', 'PM', 'NT' for display
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    timezone VARCHAR(50) DEFAULT 'America/Los_Angeles',
    description TEXT,
    color VARCHAR(20) DEFAULT '#00FFFF',  -- For UI display
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed default shifts
INSERT INTO shift_definitions (shift_name, shift_code, start_time, end_time, description, color) VALUES
    ('Morning', 'AM', '06:00:00', '14:00:00', 'Early shift covering business hours start', '#00ff41'),
    ('Afternoon', 'PM', '14:00:00', '22:00:00', 'Main business hours and evening coverage', '#00FFFF'),
    ('Night', 'NT', '22:00:00', '06:00:00', 'Overnight maintenance and off-hours support', '#FF00FF')
ON CONFLICT (shift_name) DO NOTHING;

-- =============================================================================
-- AGENT SHIFT ASSIGNMENTS TABLE
-- =============================================================================
-- Maps agents to shifts with day-of-week granularity

CREATE TABLE IF NOT EXISTS agent_shifts (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    shift_id INTEGER NOT NULL REFERENCES shift_definitions(id) ON DELETE CASCADE,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE SET NULL,
    day_of_week INTEGER CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Sun, 1=Mon, ..., 6=Sat (NULL = all days)
    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_until DATE,  -- NULL means indefinite
    is_primary BOOLEAN DEFAULT true,  -- Primary or backup role for that shift
    rotation_group VARCHAR(50),  -- For rotation scheduling (e.g., 'Group A', 'Group B')
    priority INTEGER DEFAULT 1,  -- Lower = higher priority for routing
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100) DEFAULT 'system',
    CONSTRAINT unique_agent_shift_day UNIQUE(agent_id, shift_id, day_of_week, effective_from)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_agent_shifts_agent ON agent_shifts(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_shifts_shift ON agent_shifts(shift_id);
CREATE INDEX IF NOT EXISTS idx_agent_shifts_station ON agent_shifts(station_id);
CREATE INDEX IF NOT EXISTS idx_agent_shifts_effective ON agent_shifts(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_agent_shifts_primary ON agent_shifts(is_primary) WHERE is_primary = true;

-- =============================================================================
-- SHIFT ROTATION SCHEDULES TABLE
-- =============================================================================
-- Manages automatic rotation of shift assignments

CREATE TABLE IF NOT EXISTS shift_rotations (
    id SERIAL PRIMARY KEY,
    rotation_name VARCHAR(100) NOT NULL,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    rotation_pattern JSONB NOT NULL,  -- e.g., ["Group A", "Group B", "Group C"] for 3-week rotation
    rotation_interval_days INTEGER DEFAULT 7,  -- How often to rotate (7 = weekly)
    current_position INTEGER DEFAULT 0,  -- Current index in rotation_pattern
    last_rotated_at TIMESTAMP,
    next_rotation_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    auto_rotate BOOLEAN DEFAULT true,  -- If true, system automatically rotates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_station_rotation UNIQUE(station_id, rotation_name)
);

CREATE INDEX IF NOT EXISTS idx_shift_rotations_station ON shift_rotations(station_id);
CREATE INDEX IF NOT EXISTS idx_shift_rotations_next ON shift_rotations(next_rotation_at) WHERE is_active = true;

-- =============================================================================
-- SHIFT CONFLICTS TABLE
-- =============================================================================
-- Tracks detected scheduling conflicts

CREATE TABLE IF NOT EXISTS shift_conflicts (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    shift_id INTEGER REFERENCES shift_definitions(id) ON DELETE CASCADE,
    conflict_date DATE NOT NULL,
    conflict_type VARCHAR(50) NOT NULL,  -- 'overlap', 'understaffed', 'overstaffed', 'no_backup', 'consecutive_shifts', 'iaae_violation'
    severity VARCHAR(20) DEFAULT 'warning',  -- 'info', 'warning', 'critical'
    description TEXT,
    details JSONB,  -- Additional conflict details
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),
    resolution_note TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shift_conflicts_unresolved ON shift_conflicts(resolved) WHERE resolved = false;
CREATE INDEX IF NOT EXISTS idx_shift_conflicts_agent ON shift_conflicts(agent_id);
CREATE INDEX IF NOT EXISTS idx_shift_conflicts_station ON shift_conflicts(station_id);
CREATE INDEX IF NOT EXISTS idx_shift_conflicts_date ON shift_conflicts(conflict_date);
CREATE INDEX IF NOT EXISTS idx_shift_conflicts_severity ON shift_conflicts(severity);

-- =============================================================================
-- SHIFT HISTORY TABLE
-- =============================================================================
-- Audit trail for shift changes

CREATE TABLE IF NOT EXISTS shift_history (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    shift_id INTEGER REFERENCES shift_definitions(id) ON DELETE SET NULL,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL,  -- 'assigned', 'removed', 'rotated', 'modified'
    old_values JSONB,
    new_values JSONB,
    reason TEXT,
    performed_by VARCHAR(100) DEFAULT 'system',
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shift_history_agent ON shift_history(agent_id);
CREATE INDEX IF NOT EXISTS idx_shift_history_performed_at ON shift_history(performed_at);

-- =============================================================================
-- VIEWS
-- =============================================================================

-- View: Currently on-duty agents based on shift assignments
CREATE OR REPLACE VIEW v_agents_on_duty AS
SELECT
    a.id AS agent_id,
    a.name AS agent_name,
    a.department,
    a.worker_type,
    a.model,
    a.status,
    sd.shift_name,
    sd.shift_code,
    sd.start_time,
    sd.end_time,
    ash.is_primary,
    ash.station_id,
    bs.station_name,
    CASE
        WHEN sd.start_time <= sd.end_time THEN
            CURRENT_TIME BETWEEN sd.start_time AND sd.end_time
        ELSE  -- Night shift spans midnight
            CURRENT_TIME >= sd.start_time OR CURRENT_TIME <= sd.end_time
    END AS is_currently_on_shift
FROM agents a
JOIN agent_shifts ash ON a.id = ash.agent_id
JOIN shift_definitions sd ON ash.shift_id = sd.id
LEFT JOIN bridge_stations bs ON ash.station_id = bs.id
WHERE
    a.status = 'active'
    AND sd.is_active = true
    AND ash.effective_from <= CURRENT_DATE
    AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
    AND (ash.day_of_week IS NULL OR ash.day_of_week = EXTRACT(DOW FROM CURRENT_DATE));

-- View: Shift calendar for the current week
CREATE OR REPLACE VIEW v_shift_calendar_week AS
WITH week_days AS (
    SELECT
        generate_series(0, 6) AS day_num,
        to_char(CURRENT_DATE + generate_series(0, 6), 'Dy') AS day_name,
        CURRENT_DATE + generate_series(0, 6) AS shift_date
)
SELECT
    wd.day_num,
    wd.day_name,
    wd.shift_date,
    sd.id AS shift_id,
    sd.shift_name,
    sd.shift_code,
    COALESCE(
        (SELECT json_agg(json_build_object(
            'agent_id', a.id,
            'agent_name', a.name,
            'is_primary', ash.is_primary,
            'station_id', ash.station_id
        ))
        FROM agent_shifts ash
        JOIN agents a ON ash.agent_id = a.id
        WHERE ash.shift_id = sd.id
        AND a.status = 'active'
        AND ash.effective_from <= wd.shift_date
        AND (ash.effective_until IS NULL OR ash.effective_until >= wd.shift_date)
        AND (ash.day_of_week IS NULL OR ash.day_of_week = wd.day_num)),
        '[]'::json
    ) AS assigned_agents
FROM week_days wd
CROSS JOIN shift_definitions sd
WHERE sd.is_active = true
ORDER BY wd.day_num, sd.start_time;

-- View: Station staffing summary
CREATE OR REPLACE VIEW v_station_staffing AS
SELECT
    bs.id AS station_id,
    bs.station_code,
    bs.station_name,
    sd.id AS shift_id,
    sd.shift_name,
    sd.shift_code,
    COUNT(CASE WHEN ash.is_primary = true THEN 1 END) AS primary_count,
    COUNT(CASE WHEN ash.is_primary = false THEN 1 END) AS backup_count,
    COUNT(*) AS total_assigned,
    CASE
        WHEN COUNT(CASE WHEN ash.is_primary = true THEN 1 END) = 0 THEN 'understaffed'
        WHEN COUNT(CASE WHEN ash.is_primary = false THEN 1 END) = 0 THEN 'no_backup'
        WHEN COUNT(*) > 3 THEN 'overstaffed'
        ELSE 'adequate'
    END AS staffing_status
FROM bridge_stations bs
CROSS JOIN shift_definitions sd
LEFT JOIN agent_shifts ash ON bs.id = ash.station_id
    AND sd.id = ash.shift_id
    AND ash.effective_from <= CURRENT_DATE
    AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
LEFT JOIN agents a ON ash.agent_id = a.id AND a.status = 'active'
WHERE bs.is_active = true AND sd.is_active = true
GROUP BY bs.id, bs.station_code, bs.station_name, sd.id, sd.shift_name, sd.shift_code
ORDER BY bs.station_code, sd.start_time;

-- View: Unresolved conflicts summary
CREATE OR REPLACE VIEW v_unresolved_shift_conflicts AS
SELECT
    sc.id,
    sc.conflict_type,
    sc.severity,
    sc.description,
    sc.conflict_date,
    sc.detected_at,
    a.name AS agent_name,
    bs.station_name,
    sd.shift_name,
    sc.details
FROM shift_conflicts sc
LEFT JOIN agents a ON sc.agent_id = a.id
LEFT JOIN bridge_stations bs ON sc.station_id = bs.id
LEFT JOIN shift_definitions sd ON sc.shift_id = sd.id
WHERE sc.resolved = false
ORDER BY
    CASE sc.severity
        WHEN 'critical' THEN 1
        WHEN 'warning' THEN 2
        ELSE 3
    END,
    sc.detected_at DESC;

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Function: Get agents available at a specific time
CREATE OR REPLACE FUNCTION get_agents_on_duty(
    p_time TIME DEFAULT CURRENT_TIME,
    p_day_of_week INTEGER DEFAULT EXTRACT(DOW FROM CURRENT_DATE)::INTEGER,
    p_station_id INTEGER DEFAULT NULL
)
RETURNS TABLE (
    agent_id INTEGER,
    agent_name VARCHAR,
    department VARCHAR,
    model VARCHAR,
    shift_name VARCHAR,
    is_primary BOOLEAN,
    station_id INTEGER,
    station_name VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.id,
        a.name,
        a.department,
        a.model,
        sd.shift_name,
        ash.is_primary,
        ash.station_id,
        bs.station_name
    FROM agents a
    JOIN agent_shifts ash ON a.id = ash.agent_id
    JOIN shift_definitions sd ON ash.shift_id = sd.id
    LEFT JOIN bridge_stations bs ON ash.station_id = bs.id
    WHERE
        a.status = 'active'
        AND sd.is_active = true
        AND ash.effective_from <= CURRENT_DATE
        AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
        AND (ash.day_of_week IS NULL OR ash.day_of_week = p_day_of_week)
        AND (p_station_id IS NULL OR ash.station_id = p_station_id)
        AND (
            CASE
                WHEN sd.start_time <= sd.end_time THEN
                    p_time BETWEEN sd.start_time AND sd.end_time
                ELSE  -- Night shift spans midnight
                    p_time >= sd.start_time OR p_time <= sd.end_time
            END
        )
    ORDER BY ash.is_primary DESC, ash.priority ASC;
END;
$$ LANGUAGE plpgsql;

-- Function: Detect shift conflicts
CREATE OR REPLACE FUNCTION detect_shift_conflicts()
RETURNS INTEGER AS $$
DECLARE
    conflict_count INTEGER := 0;
    r RECORD;
BEGIN
    -- Clear old conflicts for re-detection (keep resolved ones)
    DELETE FROM shift_conflicts WHERE resolved = false AND detected_at < CURRENT_TIMESTAMP - INTERVAL '1 hour';

    -- 1. Detect understaffed stations (no primary agent)
    FOR r IN
        SELECT station_id, shift_id, station_name, shift_name
        FROM v_station_staffing
        WHERE primary_count = 0
    LOOP
        INSERT INTO shift_conflicts (station_id, shift_id, conflict_date, conflict_type, severity, description)
        VALUES (r.station_id, r.shift_id, CURRENT_DATE, 'understaffed', 'critical',
                format('Station %s has no primary agent for %s shift', r.station_name, r.shift_name))
        ON CONFLICT DO NOTHING;
        conflict_count := conflict_count + 1;
    END LOOP;

    -- 2. Detect no backup situations
    FOR r IN
        SELECT station_id, shift_id, station_name, shift_name
        FROM v_station_staffing
        WHERE primary_count > 0 AND backup_count = 0
    LOOP
        INSERT INTO shift_conflicts (station_id, shift_id, conflict_date, conflict_type, severity, description)
        VALUES (r.station_id, r.shift_id, CURRENT_DATE, 'no_backup', 'warning',
                format('Station %s has no backup agent for %s shift', r.station_name, r.shift_name))
        ON CONFLICT DO NOTHING;
        conflict_count := conflict_count + 1;
    END LOOP;

    -- 3. Detect overstaffed stations
    FOR r IN
        SELECT station_id, shift_id, station_name, shift_name, total_assigned
        FROM v_station_staffing
        WHERE total_assigned > 3
    LOOP
        INSERT INTO shift_conflicts (station_id, shift_id, conflict_date, conflict_type, severity, description, details)
        VALUES (r.station_id, r.shift_id, CURRENT_DATE, 'overstaffed', 'info',
                format('Station %s has %s agents for %s shift (>3)', r.station_name, r.total_assigned, r.shift_name),
                json_build_object('agent_count', r.total_assigned))
        ON CONFLICT DO NOTHING;
        conflict_count := conflict_count + 1;
    END LOOP;

    -- 4. Detect agents working consecutive shifts (IAAE violation)
    FOR r IN
        SELECT
            a.id AS agent_id,
            a.name AS agent_name,
            array_agg(sd.shift_name ORDER BY sd.start_time) AS shifts
        FROM agents a
        JOIN agent_shifts ash ON a.id = ash.agent_id
        JOIN shift_definitions sd ON ash.shift_id = sd.id
        WHERE
            a.status = 'active'
            AND ash.effective_from <= CURRENT_DATE
            AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
            AND (ash.day_of_week IS NULL OR ash.day_of_week = EXTRACT(DOW FROM CURRENT_DATE))
        GROUP BY a.id, a.name
        HAVING COUNT(*) > 1
    LOOP
        INSERT INTO shift_conflicts (agent_id, conflict_date, conflict_type, severity, description, details)
        VALUES (r.agent_id, CURRENT_DATE, 'consecutive_shifts', 'warning',
                format('Agent %s assigned to multiple shifts on same day', r.agent_name),
                json_build_object('shifts', r.shifts))
        ON CONFLICT DO NOTHING;
        conflict_count := conflict_count + 1;
    END LOOP;

    RETURN conflict_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Advance shift rotation
CREATE OR REPLACE FUNCTION advance_shift_rotation(p_rotation_id INTEGER)
RETURNS BOOLEAN AS $$
DECLARE
    v_pattern JSONB;
    v_current_pos INTEGER;
    v_new_pos INTEGER;
    v_pattern_length INTEGER;
BEGIN
    SELECT rotation_pattern, current_position INTO v_pattern, v_current_pos
    FROM shift_rotations WHERE id = p_rotation_id AND is_active = true;

    IF NOT FOUND THEN
        RETURN false;
    END IF;

    v_pattern_length := jsonb_array_length(v_pattern);
    v_new_pos := (v_current_pos + 1) % v_pattern_length;

    UPDATE shift_rotations
    SET
        current_position = v_new_pos,
        last_rotated_at = CURRENT_TIMESTAMP,
        next_rotation_at = CURRENT_TIMESTAMP + (rotation_interval_days || ' days')::INTERVAL,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = p_rotation_id;

    -- Log the rotation
    INSERT INTO shift_history (action, new_values, reason, performed_by)
    VALUES ('rotated',
            json_build_object('rotation_id', p_rotation_id, 'new_position', v_new_pos),
            'Scheduled rotation advance',
            'system');

    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGER FOR UPDATED_AT
-- =============================================================================

CREATE OR REPLACE FUNCTION update_shift_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER shift_definitions_updated
    BEFORE UPDATE ON shift_definitions
    FOR EACH ROW EXECUTE FUNCTION update_shift_timestamp();

CREATE TRIGGER agent_shifts_updated
    BEFORE UPDATE ON agent_shifts
    FOR EACH ROW EXECUTE FUNCTION update_shift_timestamp();

CREATE TRIGGER shift_rotations_updated
    BEFORE UPDATE ON shift_rotations
    FOR EACH ROW EXECUTE FUNCTION update_shift_timestamp();

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE shift_definitions IS 'Defines available shift types (Morning, Afternoon, Night)';
COMMENT ON TABLE agent_shifts IS 'Maps agents to shifts with optional day-of-week specificity';
COMMENT ON TABLE shift_rotations IS 'Manages automatic rotation of shift groups';
COMMENT ON TABLE shift_conflicts IS 'Tracks detected scheduling conflicts for resolution';
COMMENT ON TABLE shift_history IS 'Audit trail for all shift changes';
COMMENT ON VIEW v_agents_on_duty IS 'Shows agents currently on-duty based on current time';
COMMENT ON VIEW v_shift_calendar_week IS 'Weekly calendar view of shift assignments';
COMMENT ON VIEW v_station_staffing IS 'Station staffing status per shift';
COMMENT ON VIEW v_unresolved_shift_conflicts IS 'Active conflicts requiring attention';
COMMENT ON FUNCTION get_agents_on_duty IS 'Returns agents available at a given time, optionally filtered by station';
COMMENT ON FUNCTION detect_shift_conflicts IS 'Scans for scheduling conflicts and logs them';
COMMENT ON FUNCTION advance_shift_rotation IS 'Advances a rotation schedule to the next position';

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================
