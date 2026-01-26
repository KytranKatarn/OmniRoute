-- Migration 039: Station Assignment UI - Drag-and-Drop Support
-- Date: 2026-01-19
-- Purpose: Add training assignments table, update station assignments for drag-drop UI

-- =============================================================================
-- 1. CREATE TRAINING_ASSIGNMENTS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS training_assignments (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(100),
    target_proficiency INTEGER CHECK (target_proficiency BETWEEN 1 AND 5),
    current_proficiency INTEGER DEFAULT 1 CHECK (current_proficiency BETWEEN 1 AND 5),
    status VARCHAR(30) DEFAULT 'in_progress' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    started_at TIMESTAMP DEFAULT NOW(),
    target_completion TIMESTAMP,
    completed_at TIMESTAMP,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_training_assignments_agent ON training_assignments(agent_id);
CREATE INDEX IF NOT EXISTS idx_training_assignments_status ON training_assignments(status);
CREATE INDEX IF NOT EXISTS idx_training_assignments_skill ON training_assignments(skill_name);

-- =============================================================================
-- 2. MODIFY STATION_ASSIGNMENTS TABLE
-- =============================================================================

-- Add columns for fixed assignments and role types
ALTER TABLE station_assignments
ADD COLUMN IF NOT EXISTS is_fixed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS role_type VARCHAR(30) DEFAULT 'standard';

-- role_type values: standard, commander, co-commander, assistant, backup

COMMENT ON COLUMN station_assignments.is_fixed IS 'If TRUE, agent cannot be moved from this station via drag-drop';
COMMENT ON COLUMN station_assignments.role_type IS 'Role type: standard, commander, co-commander, assistant, backup';

-- =============================================================================
-- 3. CREATE VIEW: LOUNGE AGENTS (Currently Resting)
-- =============================================================================

CREATE OR REPLACE VIEW v_lounge_agents AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.first_name,
    a.last_name,
    a.avatar_url,
    a.department,
    a.model,
    a.worker_type,
    arc.id as rest_cycle_id,
    arc.rest_type,
    arc.reason as rest_reason,
    arc.started_at as rest_started,
    EXTRACT(EPOCH FROM (NOW() - arc.started_at)) / 3600 as hours_resting,
    CASE
        WHEN arc.rest_type = 'forced' THEN TRUE
        ELSE FALSE
    END as is_locked,
    aes.stress_level,
    aes.energy_level
FROM agent_rest_cycles arc
JOIN agents a ON arc.agent_id = a.id
LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
WHERE arc.ended_at IS NULL
AND a.status = 'active';

-- =============================================================================
-- 4. CREATE VIEW: UNASSIGNED AGENTS POOL
-- =============================================================================

CREATE OR REPLACE VIEW v_unassigned_agents AS
SELECT
    a.id,
    a.name,
    a.first_name,
    a.last_name,
    a.avatar_url,
    a.department,
    a.title,
    a.model,
    a.worker_type,
    a.tier,
    COALESCE(aes.stress_level, 0) as stress_level,
    COALESCE(aes.energy_level, 1) as energy_level
FROM agents a
LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
LEFT JOIN training_assignments ta ON a.id = ta.agent_id AND ta.status IN ('pending', 'in_progress')
LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
WHERE a.status = 'active'
AND sa.id IS NULL
AND ta.id IS NULL
AND arc.id IS NULL
ORDER BY a.department, a.name;

-- =============================================================================
-- 5. CREATE VIEW: TRAINING ROOM AGENTS
-- =============================================================================

CREATE OR REPLACE VIEW v_training_room_agents AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.first_name,
    a.last_name,
    a.avatar_url,
    a.department,
    ta.id as training_id,
    ta.skill_name,
    ta.skill_category,
    ta.current_proficiency,
    ta.target_proficiency,
    ta.status as training_status,
    ta.started_at as training_started,
    EXTRACT(EPOCH FROM (NOW() - ta.started_at)) / 3600 as hours_training,
    ta.notes as training_notes,
    COALESCE(aes.stress_level, 0) as stress_level,
    COALESCE(aes.energy_level, 1) as energy_level
FROM training_assignments ta
JOIN agents a ON ta.agent_id = a.id
LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
WHERE ta.status IN ('pending', 'in_progress')
AND a.status = 'active'
ORDER BY ta.started_at DESC;

-- =============================================================================
-- 6. SET UP COMMAND STATION FIXED ASSIGNMENTS
-- =============================================================================

-- First, ensure COMMAND station exists and get its ID
DO $$
DECLARE
    v_command_station_id INTEGER;
    v_archie_id INTEGER := 77;  -- A.R.C.H.I.E.
    v_kytran_id INTEGER := 78;  -- Kytran
BEGIN
    -- Get Command station ID
    SELECT id INTO v_command_station_id FROM bridge_stations WHERE station_code = 'COMMAND';

    IF v_command_station_id IS NOT NULL THEN
        -- Set A.R.C.H.I.E. as Commander (fixed)
        INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_fixed, role_type, is_active, priority)
        VALUES (v_command_station_id, v_archie_id, 'primary', TRUE, 'commander', TRUE, 1)
        ON CONFLICT (station_id, agent_id) DO UPDATE SET
            is_fixed = TRUE,
            role_type = 'commander',
            is_active = TRUE,
            priority = 1;

        -- Set Kytran as Co-Commander (fixed)
        INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_fixed, role_type, is_active, priority)
        VALUES (v_command_station_id, v_kytran_id, 'primary', TRUE, 'co-commander', TRUE, 2)
        ON CONFLICT (station_id, agent_id) DO UPDATE SET
            is_fixed = TRUE,
            role_type = 'co-commander',
            is_active = TRUE,
            priority = 2;

        RAISE NOTICE 'Command station assignments set: ARCHIE (commander), Kytran (co-commander)';
    ELSE
        RAISE WARNING 'COMMAND station not found - skipping fixed assignments';
    END IF;
END $$;

-- =============================================================================
-- 7. CREATE VIEW: FULL STATION LAYOUT
-- =============================================================================

CREATE OR REPLACE VIEW v_station_full_layout AS
SELECT
    bs.id as station_id,
    bs.station_code,
    bs.station_name,
    bs.full_name,
    bs.icon,
    bs.color,
    bs.position_row,
    bs.position_order,
    COALESCE(
        json_agg(
            json_build_object(
                'assignment_id', sa.id,
                'agent_id', a.id,
                'agent_name', a.name,
                'first_name', a.first_name,
                'last_name', a.last_name,
                'avatar_url', a.avatar_url,
                'department', a.department,
                'model', a.model,
                'assignment_type', sa.assignment_type,
                'role_type', COALESCE(sa.role_type, 'standard'),
                'is_fixed', COALESCE(sa.is_fixed, FALSE),
                'priority', sa.priority,
                'stress_level', COALESCE(aes.stress_level, 0),
                'energy_level', COALESCE(aes.energy_level, 1)
            ) ORDER BY sa.priority, sa.is_fixed DESC
        ) FILTER (WHERE sa.id IS NOT NULL),
        '[]'::json
    ) as assigned_agents
FROM bridge_stations bs
LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = TRUE
LEFT JOIN agents a ON sa.agent_id = a.id AND a.status = 'active'
LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
GROUP BY bs.id, bs.station_code, bs.station_name, bs.full_name, bs.icon, bs.color, bs.position_row, bs.position_order
ORDER BY bs.position_row, bs.position_order;

-- =============================================================================
-- 8. GRANT PERMISSIONS
-- =============================================================================

GRANT SELECT ON v_lounge_agents TO archie;
GRANT SELECT ON v_unassigned_agents TO archie;
GRANT SELECT ON v_training_room_agents TO archie;
GRANT SELECT ON v_station_full_layout TO archie;
GRANT ALL ON training_assignments TO archie;
GRANT USAGE, SELECT ON SEQUENCE training_assignments_id_seq TO archie;

-- =============================================================================
-- 9. VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_archie_fixed BOOLEAN;
    v_kytran_fixed BOOLEAN;
BEGIN
    SELECT is_fixed INTO v_archie_fixed FROM station_assignments WHERE agent_id = 77 AND is_active = TRUE;
    SELECT is_fixed INTO v_kytran_fixed FROM station_assignments WHERE agent_id = 78 AND is_active = TRUE;

    IF v_archie_fixed AND v_kytran_fixed THEN
        RAISE NOTICE 'Migration 039: Station Assignment UI - COMPLETE';
        RAISE NOTICE '  - training_assignments table created';
        RAISE NOTICE '  - station_assignments updated with is_fixed, role_type columns';
        RAISE NOTICE '  - Views created: v_lounge_agents, v_unassigned_agents, v_training_room_agents, v_station_full_layout';
        RAISE NOTICE '  - Command station: ARCHIE (commander) and Kytran (co-commander) set as fixed';
    ELSE
        RAISE WARNING 'Command station fixed assignments may not be set correctly';
    END IF;
END $$;

SELECT 'Migration 039: Station Assignment UI - COMPLETE' as status;
