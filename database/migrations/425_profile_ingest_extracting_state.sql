-- 425_profile_ingest_extracting_state.sql
-- Add 'extracting' transient state to profile_ingest_ledger for fleet batch dispatch.
-- Project #377 — Memory Vault Phase 2 fleet fan-out.
--
-- 'extracting' is set atomically by fleet_batch_dispatcher.claim_sub_batches() when
-- a worker thread claims a row before dispatching to a fleet node. The progress
-- observer resets rows stuck in 'extracting' for > 15 minutes (crash recovery).
--
-- Extended state machine:
--   new -> triaged_important | triaged_bulk | triaged_skip
--   triaged_important -> extracting  (fleet batch claim, transient)
--   extracting -> extracted | extract_error
--
-- No CHECK constraint exists on state (it is a plain TEXT column), so no schema
-- change is needed beyond the index. Idempotent.

-- Partial index for the observer's stuck-row cleanup query:
--   UPDATE ... WHERE state = 'extracting' AND claimed_at < now() - INTERVAL '15 minutes'
CREATE INDEX IF NOT EXISTS idx_ledger_extracting_claimed
    ON profile_ingest_ledger (claimed_at)
    WHERE state = 'extracting';

-- Document the extended state machine on the column.
COMMENT ON COLUMN profile_ingest_ledger.state IS
    'State machine: new -> triaged_important | triaged_bulk | triaged_skip'
    ' -> extracting (fleet batch transient, 15min auto-reset on stall)'
    ' -> extracted | extract_error';
