-- 408_agentic_tool_search.sql
-- Task #3534 Phase 1: feature flag for the agentic tool-use KB search loop.
-- Default OFF — tool-capable agents (D.A.R.W.I.N. / qwen2.5:7b) only run the
-- /api/chat tool-loop when this is flipped 'true'. Idempotent; never clobbers
-- an existing value.

INSERT INTO platform_settings (key, value)
VALUES ('agentic_tool_search', 'false')
ON CONFLICT (key) DO NOTHING;
