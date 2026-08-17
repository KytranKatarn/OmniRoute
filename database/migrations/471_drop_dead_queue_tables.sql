-- 471_drop_dead_queue_tables.sql  (#5344, #5211 Batch-B queue audit 2026-07-28)
--
-- Drops THREE queue tables verified zero-writer / zero-drainer / zero rows:
--   proposal_queue    — only consumer was ProposalQueueManager (sandbox_queue.py),
--                       whose sole caller lived in _deprecated/admin_deprecated_20260113.
--                       The live sandbox path (SandboxQueue) never touched it.
--                       The class is deleted in the same PR as this migration.
--   call_queue        — zero code refs; schema only in 002_telephony_system.sql.
--                       DISTINCT from agent_call_queue, which stays.
--   ft_training_jobs  — zero refs; migration 042 fine-tuning was never built.
--
-- Per feedback_bulk-ops-are-n-decisions, each table is INDIVIDUALLY verified
-- empty at migration time — any rows means the audit went stale and the
-- migration REFUSES rather than destroying data. Idempotent: a missing table
-- is treated as already-dropped.

DO $$
DECLARE
    t TEXT;
    n BIGINT;
BEGIN
    -- ft_training_jobs has two dependents the audit missed (caught in the
    -- ROLLBACK rehearsal of this migration): view v_ft_user_stats (zero code
    -- refs) and an FK from ft_models (zero code refs, verified EMPTY below).
    -- Both belong to the same never-built migration-042 fine-tuning system.
    -- Only the BLOCKERS are cleared here; the remaining ft_* tables
    -- (ft_models/ft_datasets/ft_evaluations/ft_base_models) are OUT OF SCOPE
    -- for #5344 — ft_base_models carries seed rows and none were audited.
    IF to_regclass('public.ft_models') IS NOT NULL THEN
        SELECT count(*) INTO n FROM ft_models;
        IF n > 0 THEN
            RAISE EXCEPTION 'ft_models has % row(s) — refusing to detach its FK', n;
        END IF;
        ALTER TABLE ft_models DROP CONSTRAINT IF EXISTS ft_models_training_job_id_fkey;
    END IF;
    DROP VIEW IF EXISTS v_ft_user_stats;

    FOREACH t IN ARRAY ARRAY['proposal_queue', 'call_queue', 'ft_training_jobs'] LOOP
        IF to_regclass('public.' || t) IS NULL THEN
            RAISE NOTICE '% already absent — nothing to drop', t;
            CONTINUE;
        END IF;
        EXECUTE format('SELECT count(*) FROM %I', t) INTO n;
        IF n > 0 THEN
            RAISE EXCEPTION '% has % row(s) — the zero-writer audit is stale; refusing to drop', t, n;
        END IF;
        EXECUTE format('DROP TABLE %I', t);
        RAISE NOTICE 'dropped % (verified empty)', t;
    END LOOP;
END $$;
