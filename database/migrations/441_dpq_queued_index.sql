-- 441_dpq_queued_index.sql
-- #4542 — retention/prune support.
-- dispatch_pending_queue ages on `queued_at` but had no index on it, so the
-- retention prune's `WHERE queued_at < NOW() - interval` would seq-scan the
-- whole table. bridge_jobs already has idx_bridge_jobs_created (created_at).
-- Idempotent.

CREATE INDEX IF NOT EXISTS idx_dpq_queued
    ON dispatch_pending_queue (queued_at);
