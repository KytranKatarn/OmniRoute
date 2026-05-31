-- 409_agent_kb_writes.sql
-- Task #3534 Phase 3: agent-proposed KB writes (quarantine + auto-review).
-- Adds a per-agent daily write quota counter and the write-tool feature flag.
-- Idempotent.

-- Per-agent daily KB-write quota (mirrors the token_reset pattern).
ALTER TABLE agent_budgets
    ADD COLUMN IF NOT EXISTS kb_writes_today INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_budgets
    ADD COLUMN IF NOT EXISTS kb_writes_reset_at TIMESTAMP;

-- Write-tool flag — distinct from the read flag (agentic_tool_search) because
-- writes are higher-risk. Default OFF.
INSERT INTO platform_settings (key, value)
VALUES ('agentic_tool_write', 'false')
ON CONFLICT (key) DO NOTHING;

-- Helpful index for the auto-review job (find pending agent-proposed rows fast).
CREATE INDEX IF NOT EXISTS idx_kb_agent_proposed_pending
    ON knowledge_base (created_at)
    WHERE source_type = 'agent_proposed' AND review_status = 'pending';
