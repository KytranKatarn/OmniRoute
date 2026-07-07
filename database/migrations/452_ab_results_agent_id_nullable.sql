-- 452: action_benchmark_results.agent_id nullable
--
-- The A/B testing lane (Agent Academy) compares two MODELS, not two agents, so
-- its result rows have no real agent. The endpoint inserted agent_id=0, which
-- violates action_benchmark_results_agent_id_fkey (no agent id 0 exists) and made
-- the local-vs-local A/B path error out (found running the first qwen3:8b A/B, #4708).
-- Make agent_id nullable so synthetic model rows can store NULL (the FK permits NULL);
-- real agent-benchmark rows continue to store a valid agent id.
--
-- Idempotent: DROP NOT NULL on an already-nullable column is a no-op.

ALTER TABLE action_benchmark_results ALTER COLUMN agent_id DROP NOT NULL;
