-- Migration 124: Performance-Driven Training System
-- Adds degradation tracking, failure analysis, and training timer support
-- Part of the closed loop: dispatch → fail → degrade → train → complete → restore

-- 1. New columns on training_assignments for failure-aware training
ALTER TABLE training_assignments ADD COLUMN IF NOT EXISTS failure_analysis TEXT;
ALTER TABLE training_assignments ADD COLUMN IF NOT EXISTS degradation_triggered BOOLEAN DEFAULT FALSE;
ALTER TABLE training_assignments ADD COLUMN IF NOT EXISTS failure_summary JSONB;

-- 2. Degradation tracking on agent_learning_log
ALTER TABLE agent_learning_log ADD COLUMN IF NOT EXISTS last_degraded_at TIMESTAMP;
ALTER TABLE agent_learning_log ADD COLUMN IF NOT EXISTS degradation_count INTEGER DEFAULT 0;

-- 3. Training system configuration thresholds
INSERT INTO autonomy_config (config_key, config_value, description) VALUES
    ('training_failure_threshold', '50', 'Failure rate % to trigger degradation'),
    ('training_min_tasks', '5', 'Minimum tasks before evaluating degradation'),
    ('training_lookback_days', '7', 'Days to look back for failure analysis'),
    ('training_hours_per_level', '{"2":1,"3":2,"4":4,"5":8}', 'Hours of training required per target level')
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value;

-- 4. Recreate training room view with failure analysis and degradation fields
DROP VIEW IF EXISTS v_training_room_agents;
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
    ta.target_completion,
    EXTRACT(EPOCH FROM (NOW() - ta.started_at)) / 3600 as hours_training,
    ta.notes as training_notes,
    ta.failure_analysis,
    ta.degradation_triggered,
    ta.failure_summary,
    COALESCE(aes.stress_level, 0) as stress_level,
    COALESCE(aes.energy_level, 1) as energy_level
FROM training_assignments ta
JOIN agents a ON ta.agent_id = a.id
LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
WHERE ta.status IN ('pending', 'in_progress')
AND a.status = 'active'
ORDER BY ta.started_at DESC;
