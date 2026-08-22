-- 474: backfill the machine-readable "was the code actually applied?" flag (#5899/#5808)
--
-- proposal_service.deploy_proposal() takes a backup, records "Manual deployment
-- required - automatic code application disabled for safety", and then writes
-- status='deployed'. The SAFETY behaviour is correct; the STATUS NAME is not, and
-- that one word makes every downstream count read as shipped work.
--
-- #5808 already added the honest machine-readable pair at the write site:
--     "code_applied": false, "apply_mode": "manual"
-- but only from 2026-08-19 onward (26 rows). The 344 older rows of the SAME path
-- carry the truth only as PROSE inside metadata.deployment_log, which is exactly
-- what that flag exists to avoid parsing.
--
-- This backfills the flag from the prose so one query answers the question for the
-- whole population. It does NOT change any status, and it does NOT claim anything
-- is applied — absence of the flag stays UNKNOWN, never "applied".
--
-- Idempotent: re-running is a no-op (the WHERE excludes rows that already have it).

UPDATE improvement_proposals
   SET metadata = COALESCE(metadata, '{}'::jsonb)
                  || '{"code_applied": false, "apply_mode": "manual",
                       "code_applied_backfilled_by": "migration_474"}'::jsonb
 WHERE status IN ('deployed', 'implemented')
   AND metadata->>'code_applied' IS NULL
   AND metadata::text ILIKE '%Manual deployment required%';

-- Report what moved (psql prints the row count of the UPDATE above).
-- Expected on first run: 344 rows. Second run: 0.
