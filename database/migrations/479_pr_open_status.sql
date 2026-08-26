-- 479: pr_open — proposal shipped as a branch+PR, awaiting the governed merge.
-- Spec: docs/superpowers/specs/2026-08-26-self-repair-lifecycle-completion-design.md §6.
-- Idempotent: drop+recreate the status CHECK with the one new value appended.
ALTER TABLE improvement_proposals DROP CONSTRAINT IF EXISTS improvement_proposals_status_check;
ALTER TABLE improvement_proposals ADD CONSTRAINT improvement_proposals_status_check
  CHECK (status::text = ANY (ARRAY[
    'proposed','approved','sandboxed','deployed','regression','paused_for_perf_review',
    'rejected','archived','fix_requested','pending','pending_approval','ready_for_review',
    'agent_assigned','needs_claude','pr_open'
  ]::text[]));
