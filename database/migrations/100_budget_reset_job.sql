-- Migration 100: Ensure agent_budgets has sane defaults for budget reset
-- Part of Phase 1: Agent Lifecycle Coordination
-- Idempotent: safe to run multiple times

-- Ensure all active agents have a budget row
INSERT INTO agent_budgets (agent_id, task_queue_limit, current_task_count,
                           token_limit_per_day, tokens_used_today, token_reset_at)
SELECT a.id, 10, 0, 100000, 0, NOW()
FROM agents a
LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
WHERE ab.id IS NULL AND a.status = 'active'
ON CONFLICT (agent_id) DO NOTHING;

-- Ensure token_reset_at is never null
UPDATE agent_budgets
SET token_reset_at = NOW()
WHERE token_reset_at IS NULL;

-- Add index for the budget reset query
CREATE INDEX IF NOT EXISTS idx_agent_budgets_needs_reset
ON agent_budgets (current_task_count, tokens_used_today)
WHERE current_task_count > 0 OR tokens_used_today > 0;

-- Add index for cooldown recovery query
CREATE INDEX IF NOT EXISTS idx_agents_cooldown_recovery
ON agents (shift_state, status)
WHERE shift_state = 'cooldown' AND status = 'active';
