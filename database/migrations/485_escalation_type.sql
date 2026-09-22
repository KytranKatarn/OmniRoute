-- 485 — dispatch_escalation_log gains an explicit escalation TYPE.
--
-- WHY: misroute_audit_service._floor_fallback() selected EVERY row of this table with no
-- type filter and reported the total as "floor_fallback_hits". The table's only writer is
-- the cloud/throughput path (department_dispatcher.py), so that metric has never measured a
-- floor fallback: measured 2026-09-22 over 24h, 1,291 "Throughput: awaiting cloud approval"
-- + ~54 "paid cloud approved" and ZERO floor fallbacks. The alert fired permanently against
-- a threshold of 20 while genuine floor fallbacks were unmonitored but appeared monitored.
--
-- Distinguishing them by `reason` text would be fragile — the reason string is free-form and
-- written in several places. An explicit column is the honest key.
--
-- DEFAULT 'throughput' is deliberate and backfills every existing row: every row written
-- before this migration came from the cloud/throughput writer, so 'throughput' is not a
-- guess, it is what they are.

ALTER TABLE dispatch_escalation_log
    ADD COLUMN IF NOT EXISTS escalation_type TEXT NOT NULL DEFAULT 'throughput';

-- Existing rows predate the column; they are all throughput escalations (single writer).
UPDATE dispatch_escalation_log SET escalation_type = 'throughput' WHERE escalation_type IS NULL;

-- The audit groups by (escalation_type, capability, reason) inside a time window.
CREATE INDEX IF NOT EXISTS idx_escalation_type_created
    ON dispatch_escalation_log (escalation_type, created_at DESC);

COMMENT ON COLUMN dispatch_escalation_log.escalation_type IS
    'throughput = cloud/paid escalation (department_dispatcher); floor_fallback = same-floor '
    'department substitution (orchestration_engine step 6). Added by migration 485 because the '
    'misroute audit was reporting all escalations as floor fallbacks.';
