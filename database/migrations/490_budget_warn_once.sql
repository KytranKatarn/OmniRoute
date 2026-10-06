-- Warn once per budget period, then stay quiet (DS9 PR 8)
--
-- WHY
-- ---
-- `monthly_budget_status` has returned a `warn` band at >= 80% of the monthly limit since
-- migration 106, and since #3661 that band is finally recoverable — it clears when the period
-- rolls. Recoverable made the missing half of the feature visible.
--
-- Nothing consumed the band. The only reader was a gate (`band != "block"`), so the warn band
-- was computed on every dispatch and observed by nobody. The moment anything DOES surface it —
-- a notification, a row in a UI — the obvious implementation re-announces the same provider on
-- every single dispatch for the rest of the month. One crossing, hundreds of identical alerts.
--
-- That is the shape of the bug this column fixes: the crossing is an EVENT, and events want
-- exactly one notification. Being at 85% is a STATE, and states should be read from the status
-- function rather than announced.
--
-- WHAT THIS COLUMN IS NOT
-- -----------------------
-- It is not a "last checked" stamp and it is not reset by a cleanup job. It is the time the
-- operator was last told about the warn band, and it is compared against the CURRENT period
-- start — so a stamp left over from last month simply fails the comparison and the next
-- crossing warns again. That is why the period roll in `_update_cost` does NOT clear it:
-- the comparison is the reset. Clearing it as well would be a second mechanism for one job,
-- and the two could disagree.
--
-- NULL is a legitimate state meaning "never warned", so it must warn. The claim in `_update_cost`
-- is therefore `budget_warned_at IS NULL OR budget_warned_at < period_start`.
--
-- Backfill: deliberately NONE. A NULL here means "never warned", which is the safe direction —
-- the next real crossing warns. Backfilling from `last_reset_at` would mean "already warned
-- about a crossing we never actually announced".
--
-- TIMESTAMPTZ, like `last_reset_at`, so it is comparable to the period start in the same frame
-- `_update_cost` already uses for the period comparison.

ALTER TABLE external_api_keys
    ADD COLUMN IF NOT EXISTS budget_warned_at TIMESTAMPTZ;

COMMENT ON COLUMN external_api_keys.budget_warned_at IS
    'When the operator was last notified that this provider entered the monthly warn band. '
    'NULL = never warned. Compared against the current budget period start, so a stamp from a '
    'previous period does not silence the next crossing. Written only by _update_cost, and only '
    'by the caller that wins the atomic claim.';
