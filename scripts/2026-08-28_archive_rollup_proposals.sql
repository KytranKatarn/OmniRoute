-- Task #6107: archive the legacy per-module roll-up proposals
-- (proposal_source='code_health_scan', "Code Health: N issue(s) in X").
--
-- The writer in code_metrics_service.log_audit was retired 2026-08-28: it
-- minted one roll-up proposal per audited module BESIDE the per-finding
-- proposals audit_pipeline creates from the same run — a second sheet that no
-- code path ever read (zero readers of proposal_source='code_health_scan'),
-- inflating every unfiltered Repair Bay count. improvement_proposals keyed by
-- finding_fingerprint is the one master sheet.
--
-- Run AFTER the retirement PR is merged and archie_platform/archie_scheduler
-- are restarted (the live writer would otherwise keep refreshing rows):
--   docker exec -i archie_database psql -U archie -d archie < scripts/2026-08-28_archive_rollup_proposals.sql

UPDATE improvement_proposals
   SET status = 'archived',
       metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
           'archived_by',    'rollup_writer_retired_6107',
           'archive_reason', 'duplicate per-module rollup; per-finding proposals are canonical',
           'archived_at',    NOW()::text,
           'status_before_archive', status)
 WHERE proposal_source = 'code_health_scan'
   AND status NOT IN ('archived', 'rejected', 'deployed', 'implemented')
RETURNING id, status, title;

-- REVERT (restores each row's pre-archive status):
-- UPDATE improvement_proposals
--    SET status = COALESCE(metadata->>'status_before_archive', 'proposed'),
--        metadata = metadata - 'archived_by' - 'archive_reason' - 'archived_at' - 'status_before_archive'
--  WHERE metadata->>'archived_by' = 'rollup_writer_retired_6107';
