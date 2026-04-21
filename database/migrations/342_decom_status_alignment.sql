-- Migration 342: Align `status` to `shift_state` for decommissioned agents.
--
-- Surfaced 2026-04-20 PM session: 82 agents had status='active' while
-- shift_state='decommissioned' — a drift from when decom was added as a
-- shift_state enum but status wasn't updated in lockstep. Result: the
-- Roster API and Org Chart API (which filter on status='active') still
-- surfaced these legacy agents, while the public directory view (which
-- already filters on shift_state <> 'decommissioned') correctly excluded
-- them.
--
-- Before: 139 agents appear in Roster/Org Chart, only 54 in public directory.
-- After:  ~57 agents in Roster/Org Chart, same 54 in public (minor delta
-- from barracked AI specialists that stay).
--
-- Rows affected: 78 internal + 4 contractor = 82 total.
-- None of these rows should have had active status in the first place.
--
-- Idempotent.

UPDATE agents
SET status = 'decommissioned',
    updated_at = NOW()
WHERE status = 'active'
  AND shift_state = 'decommissioned';

-- Post-migration sanity:
-- SELECT worker_type, status, shift_state, COUNT(*) FROM agents GROUP BY 1,2,3 ORDER BY 1;
-- Should show zero rows where status='active' AND shift_state='decommissioned'.
