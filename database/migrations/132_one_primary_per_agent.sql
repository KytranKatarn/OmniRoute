-- Migration 132: One Primary Per Agent Constraint
-- Enforces that each agent can only be primary at ONE station at a time.
-- Part of Bridge as Single Source of Truth initiative.

-- ============================================================
-- 1. Cleanup: For agents with multiple active primary assignments,
--    keep only the most recent one (highest id) and demote others
--    to 'auxiliary'.
-- ============================================================

-- First, identify and fix violations
DO $$
DECLARE
    _agent_id INT;
    _keep_id INT;
BEGIN
    FOR _agent_id IN
        SELECT agent_id
        FROM station_assignments
        WHERE is_active = TRUE AND assignment_type = 'primary'
        GROUP BY agent_id
        HAVING COUNT(*) > 1
    LOOP
        -- Keep the assignment with the highest id (most recent)
        SELECT id INTO _keep_id
        FROM station_assignments
        WHERE agent_id = _agent_id AND is_active = TRUE AND assignment_type = 'primary'
        ORDER BY id DESC
        LIMIT 1;

        -- Demote all other active primaries for this agent to auxiliary
        UPDATE station_assignments
        SET assignment_type = 'auxiliary'
        WHERE agent_id = _agent_id
          AND is_active = TRUE
          AND assignment_type = 'primary'
          AND id != _keep_id;

        RAISE NOTICE 'Agent % — kept primary assignment %, demoted others to auxiliary', _agent_id, _keep_id;
    END LOOP;
END $$;

-- ============================================================
-- 2. Add partial unique index: one active primary per agent
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_primary_per_agent
    ON station_assignments(agent_id)
    WHERE is_active = TRUE AND assignment_type = 'primary';
