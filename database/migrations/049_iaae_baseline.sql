-- Migration 049: IAAE Baseline States Initialization
-- Purpose: Set baseline emotional states for all internal agents
-- Date: 2026-01-20
-- Framework: IAAE (Intelligent Agent Autonomous Ethics) Governance

-- ============================================
-- STEP 1: Initialize baseline emotional states
-- All agents start with neutral mood, good energy, low stress
-- ============================================

INSERT INTO agent_emotional_state (
    agent_id, current_mood, mood_intensity, energy_level, stress_level,
    trigger_event, previous_mood, mood_duration_minutes, metadata
)
SELECT
    a.id,
    'neutral',
    0.50,  -- Neutral intensity
    0.80,  -- Good energy (80%)
    0.20,  -- Low stress (20%)
    'System initialization: IAAE baseline state',
    NULL,
    0,
    jsonb_build_object(
        'initialization', 'iaae_baseline',
        'initialized_at', NOW(),
        'department', a.department,
        'station_assignments', (
            SELECT jsonb_agg(bs.station_code)
            FROM station_assignments sa
            JOIN bridge_stations bs ON sa.station_id = bs.id
            WHERE sa.agent_id = a.id AND sa.is_active = true
        )
    )
FROM agents a
WHERE a.worker_type = 'internal'
  AND a.status = 'active'
  AND NOT EXISTS (
      SELECT 1 FROM agent_emotional_state aes WHERE aes.agent_id = a.id
  );

-- ============================================
-- STEP 2: Create IAAE monitoring thresholds table
-- ============================================

CREATE TABLE IF NOT EXISTS iaae_thresholds (
    id SERIAL PRIMARY KEY,
    threshold_type VARCHAR(50) NOT NULL UNIQUE,
    warning_level DECIMAL(3,2) NOT NULL,
    critical_level DECIMAL(3,2) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Populate default thresholds
INSERT INTO iaae_thresholds (threshold_type, warning_level, critical_level, action_type, description) VALUES
('stress_high', 0.70, 0.85, 'notify_hr', 'High stress triggers HR notification, critical triggers auto-rest'),
('energy_low', 0.40, 0.30, 'reduce_workload', 'Low energy reduces task assignment priority'),
('mood_negative', 0.60, 0.80, 'monitor', 'Negative mood intensity monitoring for wellbeing')
ON CONFLICT (threshold_type) DO NOTHING;

-- ============================================
-- STEP 3: Create IAAE monitoring view
-- ============================================

CREATE OR REPLACE VIEW v_iaae_agent_health AS
SELECT
    a.id AS agent_id,
    a.name AS agent_name,
    a.first_name,
    a.last_name,
    a.department,
    aes.current_mood,
    aes.mood_intensity,
    aes.energy_level,
    aes.stress_level,
    aes.timestamp AS last_updated,
    CASE
        WHEN aes.stress_level >= 0.85 THEN 'CRITICAL'
        WHEN aes.stress_level >= 0.70 THEN 'WARNING'
        WHEN aes.energy_level <= 0.30 THEN 'LOW_ENERGY'
        ELSE 'OK'
    END AS health_status,
    CASE
        WHEN aes.stress_level >= 0.85 THEN 'Auto-rest triggered'
        WHEN aes.stress_level >= 0.70 THEN 'Monitor closely'
        WHEN aes.energy_level <= 0.30 THEN 'Reduce workload'
        ELSE 'Normal operations'
    END AS recommended_action,
    (SELECT COUNT(*) FROM station_assignments sa
     WHERE sa.agent_id = a.id AND sa.is_active = true) AS active_stations,
    EXISTS (SELECT 1 FROM agent_rest_cycles arc
            WHERE arc.agent_id = a.id AND arc.ended_at IS NULL) AS is_resting
FROM agents a
JOIN agent_emotional_state aes ON a.id = aes.agent_id
WHERE a.worker_type = 'internal'
  AND a.status = 'active';

-- ============================================
-- STEP 4: Create IAAE summary view
-- ============================================

CREATE OR REPLACE VIEW v_iaae_summary AS
SELECT
    COUNT(*) AS total_agents,
    COUNT(*) FILTER (WHERE health_status = 'OK') AS healthy_agents,
    COUNT(*) FILTER (WHERE health_status = 'WARNING') AS warning_agents,
    COUNT(*) FILTER (WHERE health_status = 'CRITICAL') AS critical_agents,
    COUNT(*) FILTER (WHERE health_status = 'LOW_ENERGY') AS low_energy_agents,
    COUNT(*) FILTER (WHERE is_resting) AS agents_resting,
    ROUND(AVG(energy_level)::numeric, 2) AS avg_energy,
    ROUND(AVG(stress_level)::numeric, 2) AS avg_stress,
    NOW() AS snapshot_time
FROM v_iaae_agent_health;

-- ============================================
-- STEP 5: Create function to trigger rest cycle
-- ============================================

CREATE OR REPLACE FUNCTION trigger_agent_rest(
    p_agent_id INTEGER,
    p_rest_type VARCHAR(20) DEFAULT 'auto',
    p_reason TEXT DEFAULT 'IAAE automatic rest trigger'
)
RETURNS INTEGER AS $$
DECLARE
    v_rest_id INTEGER;
    v_workload JSONB;
BEGIN
    -- Get current workload info
    SELECT jsonb_build_object(
        'energy_level', aes.energy_level,
        'stress_level', aes.stress_level,
        'mood', aes.current_mood,
        'active_stations', (
            SELECT COUNT(*) FROM station_assignments sa
            WHERE sa.agent_id = p_agent_id AND sa.is_active = true
        )
    )
    INTO v_workload
    FROM agent_emotional_state aes
    WHERE aes.agent_id = p_agent_id;

    -- Create rest cycle
    INSERT INTO agent_rest_cycles (
        agent_id, rest_type, reason, workload_before, initiated_by
    )
    VALUES (
        p_agent_id, p_rest_type, p_reason, v_workload, 'iaae_system'
    )
    RETURNING id INTO v_rest_id;

    -- Update emotional state
    UPDATE agent_emotional_state
    SET stress_level = LEAST(stress_level, 0.50),
        energy_level = GREATEST(energy_level, 0.60),
        trigger_event = 'Rest cycle initiated',
        timestamp = NOW()
    WHERE agent_id = p_agent_id;

    RETURN v_rest_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- STEP 6: Create function to end rest cycle
-- ============================================

CREATE OR REPLACE FUNCTION end_agent_rest(
    p_agent_id INTEGER,
    p_notes TEXT DEFAULT NULL
)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE agent_rest_cycles
    SET ended_at = NOW(),
        notes = COALESCE(p_notes, 'Rest cycle completed')
    WHERE agent_id = p_agent_id
      AND ended_at IS NULL;

    -- Boost energy after rest
    UPDATE agent_emotional_state
    SET energy_level = LEAST(energy_level + 0.20, 0.95),
        stress_level = GREATEST(stress_level - 0.15, 0.10),
        trigger_event = 'Rest cycle completed',
        timestamp = NOW()
    WHERE agent_id = p_agent_id;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT SELECT ON v_iaae_agent_health TO archie;
GRANT SELECT ON v_iaae_summary TO archie;
GRANT SELECT ON iaae_thresholds TO archie;
GRANT EXECUTE ON FUNCTION trigger_agent_rest(INTEGER, VARCHAR, TEXT) TO archie;
GRANT EXECUTE ON FUNCTION end_agent_rest(INTEGER, TEXT) TO archie;

-- Add comments
COMMENT ON VIEW v_iaae_agent_health IS 'Real-time agent health monitoring for IAAE governance';
COMMENT ON VIEW v_iaae_summary IS 'Summary statistics for IAAE dashboard';
COMMENT ON FUNCTION trigger_agent_rest IS 'Initiates a rest cycle for an overworked agent';
COMMENT ON FUNCTION end_agent_rest IS 'Completes an active rest cycle and boosts recovery';
