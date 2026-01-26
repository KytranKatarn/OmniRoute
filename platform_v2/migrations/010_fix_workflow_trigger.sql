-- ============================================================================
-- Migration 010: Fix Workflow Trigger
-- Date: 2026-01-02
-- Purpose: Fix track_workflow_state_change trigger to not require updated_by field
-- ============================================================================

-- Drop and recreate the trigger function without updated_by dependency
CREATE OR REPLACE FUNCTION track_workflow_state_change()
RETURNS TRIGGER AS $$
DECLARE
    v_duration INTEGER;
BEGIN
    -- Only track if status actually changed
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        -- Calculate duration in previous state
        SELECT EXTRACT(EPOCH FROM (NOW() - changed_at))::INTEGER
        INTO v_duration
        FROM improvement_workflow_states
        WHERE proposal_id = NEW.id
        ORDER BY changed_at DESC
        LIMIT 1;

        -- Insert workflow state change record
        INSERT INTO improvement_workflow_states (
            proposal_id,
            from_status,
            to_status,
            changed_by,
            changed_at,
            automated,
            duration_seconds
        ) VALUES (
            NEW.id,
            OLD.status,
            NEW.status,
            NEW.proposed_by,  -- Use proposed_by instead of updated_by
            NOW(),
            false,
            v_duration
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Recreate the trigger (in case it was dropped)
DROP TRIGGER IF EXISTS trigger_track_workflow_state ON improvement_proposals;
CREATE TRIGGER trigger_track_workflow_state
    AFTER UPDATE ON improvement_proposals
    FOR EACH ROW
    EXECUTE FUNCTION track_workflow_state_change();

COMMENT ON FUNCTION track_workflow_state_change IS 'Tracks workflow state changes for improvement proposals';
