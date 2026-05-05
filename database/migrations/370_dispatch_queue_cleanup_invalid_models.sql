-- Migration 370: Reap dispatch_pending_queue rows with invalid model_needed.
--
-- Background: department_dispatcher previously queued rows with
-- model_needed='none' / '' / 'comfyui' when a non-LLM capability got an
-- Ollama-cold response. The model_dispatch_worker (15s tick) then pinged
-- Ollama with these bogus names and got HTTP 404 every cycle, polluting
-- scheduler logs and (worse) preventing real deferred drafts from getting
-- a model loaded. Tonight's outage of the SIGNAL announce-deferred path
-- traces back to 5 such rows from agent Lucia stuck since 02:42 UTC today.
--
-- Two-part fix:
--   1. CODE: department_dispatcher now refuses to queue invalid model_needed
--      rows; model_dispatch_worker._get_highest_priority_queued_model now
--      filters them out (defense in depth).
--   2. DATA (this migration): mark existing stuck rows as 'expired' so the
--      backlog drains on the next worker cycle.
--
-- Idempotent: safe to re-run; only updates status when not already terminal.

BEGIN;

UPDATE dispatch_pending_queue
   SET status = 'expired',
       completed_at = COALESCE(completed_at, NOW()),
       error = COALESCE(
           error,
           'Reaped by migration 370 — model_needed sentinel not loadable on Ollama'
       )
 WHERE status = 'queued'
   AND (
        model_needed IS NULL
     OR lower(trim(model_needed)) IN ('', 'none', 'null', 'comfyui')
   );

COMMIT;
