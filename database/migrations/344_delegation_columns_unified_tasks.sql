-- Project #276 Phase 1 — delegation columns on unified_tasks
-- Enables Claude → Archie delegation: tasks with delegation_source set
-- are picked up by the _run_delegate_task_worker loop and executed via
-- the OrchestrationEngine / dispatcher / direct MCP-tool path.
--
-- Idempotent: all columns use IF NOT EXISTS. Safe to re-run.

ALTER TABLE unified_tasks
    ADD COLUMN IF NOT EXISTS delegation_source text,
    ADD COLUMN IF NOT EXISTS delegation_args   jsonb,
    ADD COLUMN IF NOT EXISTS streaming_channel text;

-- Fast path for the worker loop — avoid full scans of the tasks table.
CREATE INDEX IF NOT EXISTS idx_unified_tasks_delegation_queue
    ON unified_tasks (status, created_at)
    WHERE delegation_source IS NOT NULL;

COMMENT ON COLUMN unified_tasks.delegation_source IS
    'Who delegated this task: claude, user_cli, telegram, web_chat, mcp_client. NULL for normal DHQ tasks.';
COMMENT ON COLUMN unified_tasks.delegation_args IS
    'JSON payload: {capability, args, reason, requested_by}. Consumed by _run_delegate_task_worker.';
COMMENT ON COLUMN unified_tasks.streaming_channel IS
    'Optional target for progress streaming: telegram:<user>, mcp:<session>, comms:<convo_id>.';
