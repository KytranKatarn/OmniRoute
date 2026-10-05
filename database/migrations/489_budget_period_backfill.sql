-- Declare a budget period for every existing provider (DS9 PR 6)
--
-- WHY
-- ---
-- `external_api_keys` has carried `budget_reset_day` and `last_reset_at` since migration 106.
-- Neither was ever written by any code. `current_month_cost_usd` had exactly one writer, and
-- it only ever accumulated:
--
--     UPDATE external_api_keys SET current_month_cost_usd = current_month_cost_usd + %s
--
-- So the monthly budget was monotonic for the lifetime of the install. `budget_reset_day`
-- was displayed in the Contractors tab and read by no logic; `last_reset_at` existed only in
-- the CREATE TABLE above. Once a provider crossed 80% it stayed in `warn` forever, and once
-- it crossed 95% it stayed in `block` forever, with no way back — a slow-motion provider
-- lockout wearing the costume of a budget guard.
--
-- (The file named `test_budget_reconcile_schedule.py` is NOT about this. It covers
-- `reconcile_task_counters` — AGENT task counters on a wall-clock schedule. Different
-- subsystem entirely, and an easy thing to mistake for coverage that does not exist.)
--
-- This migration only backfills; the reset itself is derived at read and write time in
-- `external_providers.py`, so there is no job that can fail to run.
--
-- WHY BACKFILL RATHER THAN TREATING NULL AS STALE
-- ----------------------------------------------
-- Reading a NULL `last_reset_at` as "no spend this period" would report $0.00 for every
-- provider that had genuinely accumulated cost. Under-reporting spend is the dangerous
-- direction for a money guard, so instead the migration declares the period explicitly:
-- from now, the accumulated total counts against the current period and is reset at the
-- next `budget_reset_day` boundary. Nothing is forgiven and nothing is invented.

BEGIN;

UPDATE external_api_keys
   SET last_reset_at = NOW()
 WHERE last_reset_at IS NULL;

COMMIT;
