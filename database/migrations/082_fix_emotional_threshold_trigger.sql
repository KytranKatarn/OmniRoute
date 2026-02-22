-- Migration 082: Fix emotional threshold trigger to fire on UPDATE
-- The existing trigger only fires on INSERT, but the HR tracker and
-- post-dispatch welfare updater both use UPDATE on agent_emotional_state.
-- This means stress/energy threshold breaches were never auto-logged.

DROP TRIGGER IF EXISTS trg_emotional_threshold_check ON agent_emotional_state;

CREATE TRIGGER trg_emotional_threshold_check
    AFTER INSERT OR UPDATE ON agent_emotional_state
    FOR EACH ROW
    EXECUTE FUNCTION check_emotional_thresholds();
