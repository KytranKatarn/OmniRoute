-- 447: allow the Fix Processor pipeline statuses (#4641 / Job #48 layer 3)
-- The auto-execute pipeline writes status='agent_assigned' (on dispatch) and
-- 'needs_claude' (escalation at retry cap) — neither was in the CHECK constraint,
-- so every dispatch failed with improvement_proposals_status_check (first seen on
-- the first-ever successful tick after PRs #2034/#2035 fixed layers 1-2).
-- Idempotent: drop + re-add with the two pipeline values appended.
ALTER TABLE improvement_proposals DROP CONSTRAINT IF EXISTS improvement_proposals_status_check;
ALTER TABLE improvement_proposals ADD CONSTRAINT improvement_proposals_status_check
    CHECK (status::text = ANY (ARRAY[
        'proposed', 'approved', 'sandboxed', 'deployed', 'regression',
        'paused_for_perf_review', 'rejected', 'archived', 'fix_requested',
        'pending', 'pending_approval', 'ready_for_review',
        'agent_assigned', 'needs_claude'
    ]::text[]));
