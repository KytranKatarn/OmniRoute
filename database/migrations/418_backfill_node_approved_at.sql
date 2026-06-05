-- 418_backfill_node_approved_at.sql
-- DR fleet-identity remediation (FIX2). Postmortem: .claude/dr-postmortem-and-remediation.md
--
-- The heartbeat self-heal path treats a node as "established hardware" (and therefore
-- safe to auto-re-approve on valid credentials) when it has EVER heartbeated OR carries
-- an approved_at. Several nodes approved via migration 067 were left with approved_at
-- NULL. Backfill it from created_at so the self-heal predicate is robust even for a node
-- that somehow has no last_heartbeat yet. Idempotent.

UPDATE remote_nodes
SET approved_at = COALESCE(approved_at, created_at, NOW())
WHERE approval_status = 'approved'
  AND approved_at IS NULL;
