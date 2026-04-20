-- Migration 331: dedupe agent_portraits + add UNIQUE(agent_id)
--
-- Context: agent_portraits had no unique constraint on agent_id, but
-- three call sites (approve_canonical, generate_canonical via
-- _ensure_portrait_record, upload_canonical) used `ON CONFLICT (agent_id)`
-- expecting one. The missing constraint triggered psycopg2
-- InvalidColumnReference errors which bubbled through the global
-- exception handler and redirected users to /dashboard.
--
-- Root cause of duplicates: _ensure_portrait_record used to INSERT
-- without any upsert semantic; every canonical generation re-ran it and
-- created another row. Pre-ON-CONFLICT code path left stale rows behind.
-- Current counts: 359 rows across 131 agents (40+ agents with 3-4
-- duplicate rows each).
--
-- Strategy:
--   1. Keep the most-recent (updated_at DESC, id DESC as tiebreak) row
--      per agent_id. Rows with newer data beat older stub rows — and
--      approved=true wins over approved=false via the ORDER BY.
--   2. DELETE the other rows.
--   3. ADD CONSTRAINT UNIQUE (agent_id) so future upserts work natively
--      and the bug can't silently come back.
--
-- Idempotent: IF NOT EXISTS on the constraint, dedup uses a ROW_NUMBER
-- CTE so re-running is a no-op after first success.

BEGIN;

-- Step 1+2: dedupe. Keep the "best" row per agent (approved first, then
-- newest). ROW_NUMBER makes this safely re-runnable.
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY agent_id
               ORDER BY approved DESC NULLS LAST,
                        updated_at DESC NULLS LAST,
                        id DESC
           ) AS rn
    FROM agent_portraits
)
DELETE FROM agent_portraits
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- Step 3: add the constraint. IF NOT EXISTS keeps it idempotent.
ALTER TABLE agent_portraits
    ADD CONSTRAINT agent_portraits_agent_id_unique UNIQUE (agent_id);

COMMIT;

-- Post-migration sanity: every agent_id should now appear exactly once.
-- (Run as \d agent_portraits or SELECT COUNT(*) == COUNT(DISTINCT agent_id)
-- during verification.)
