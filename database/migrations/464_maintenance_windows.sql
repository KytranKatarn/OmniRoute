-- 464 — scheduled maintenance windows with a fix manifest (task #5235)
--
-- OWNER DIRECTIVE 2026-07-26:
--   "this will allow repair bay to schedule a maintenance window now to plan and
--    deploy its fixes in its automation schedule ... it can add multiple fixes in
--    that window but to advise and coordinate before and let me know before the
--    maintenance the fix list."
--
-- WHY
-- Two problems collapse into one solution.
--
--   1. On 2026-07-25 a PLANNED power-down was read by dr-watchdog.timer as a hub
--      failure. It promoted boston-2 and blanket-flipped all 21 Beacon upstreams,
--      taking ~20 healthy hub-only services offline. Nothing malfunctioned — the
--      quorum worked exactly as designed. No vantage can tell PLANNED from DEAD.
--
--   2. Repair Bay deploys each fix whenever it happens to be ready, so N fixes are
--      N separate unannounced disruptions, each one a fresh chance to surprise DR.
--
-- Batching fixes into ONE announced window gives: one disruption instead of N, DR
-- suppressed for exactly that interval, and — the actual point — the owner sees
-- WHAT is about to change BEFORE it changes, with a chance to veto.
--
-- RELATIONSHIP TO THE AD-HOC PATH
-- services/maintenance_window_service.py already owns "suppress DR for work
-- happening NOW" (start/heartbeat/status/end + a fail-open context manager).
-- These tables add the PLANNED, future-dated case. open_scheduled() delegates to
-- the existing start_window() so DR suppression — and its mandatory verification
-- that the watchdog actually reports itself snoozed — is never duplicated.

BEGIN;

CREATE TABLE IF NOT EXISTS maintenance_windows (
    id                   SERIAL PRIMARY KEY,
    scheduled_start      TIMESTAMPTZ NOT NULL,
    duration_minutes     INTEGER     NOT NULL DEFAULT 90,
    -- planned   : created, manifest may still be growing
    -- announced : the owner has been shown the fix list (advance notice sent)
    -- open      : DR suppression armed AND VERIFIED; work in progress
    -- closed    : finished, per-item outcomes recorded
    -- cancelled : never opened
    status               VARCHAR(16) NOT NULL DEFAULT 'planned',
    reason               TEXT,
    created_by           VARCHAR(64) NOT NULL DEFAULT 'repair_bay',
    announced_at         TIMESTAMPTZ,
    opened_at            TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    -- Mirrors start_window()'s contract: a window must NOT be treated as open
    -- unless the watchdog itself confirmed suppression. Writing a file is not
    -- proof it is honoured.
    suppression_verified BOOLEAN     NOT NULL DEFAULT FALSE,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT maintenance_windows_status_chk
        CHECK (status IN ('planned', 'announced', 'open', 'closed', 'cancelled')),
    CONSTRAINT maintenance_windows_duration_chk
        CHECK (duration_minutes > 0 AND duration_minutes <= 1440)
);

-- The fix list. Repair Bay appends as it decides what to ship.
CREATE TABLE IF NOT EXISTS maintenance_window_items (
    id           SERIAL PRIMARY KEY,
    window_id    INTEGER NOT NULL REFERENCES maintenance_windows(id) ON DELETE CASCADE,
    item_type    VARCHAR(16) NOT NULL DEFAULT 'other',
    ref          VARCHAR(128),          -- PR number, proposal id, migration name...
    title        TEXT        NOT NULL,
    added_by     VARCHAR(64) NOT NULL DEFAULT 'repair_bay',
    added_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Per-item outcome. "window closed" is not a result; WHAT shipped is.
    status       VARCHAR(16) NOT NULL DEFAULT 'planned',
    notes        TEXT,
    CONSTRAINT maintenance_window_items_type_chk
        CHECK (item_type IN ('pr', 'proposal', 'migration', 'deploy', 'other')),
    CONSTRAINT maintenance_window_items_status_chk
        CHECK (status IN ('planned', 'deployed', 'skipped', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_maintenance_windows_status_start
    ON maintenance_windows (status, scheduled_start);
CREATE INDEX IF NOT EXISTS idx_maintenance_window_items_window
    ON maintenance_window_items (window_id);

-- At most ONE window may be open at a time. Two overlapping windows would each
-- believe they own DR suppression, and the first to close would disarm the other
-- (the same "two writers, last one wins" shape as the #2465 elbow-state race).
CREATE UNIQUE INDEX IF NOT EXISTS idx_maintenance_windows_single_open
    ON maintenance_windows ((status)) WHERE status = 'open';

COMMENT ON TABLE maintenance_windows IS
    'Planned maintenance windows (task #5235). Repair Bay schedules one, batches fixes '
    'into it, and the owner is shown the manifest BEFORE it opens. Ad-hoc "suppress DR '
    'right now" lives in services/maintenance_window_service.py.';
COMMENT ON COLUMN maintenance_windows.suppression_verified IS
    'TRUE only when a real dr_watchdog.sh cycle reported itself snoozed/disabled. '
    'Writing the flag file is NOT proof it is honoured.';
COMMENT ON COLUMN maintenance_windows.announced_at IS
    'When the owner was shown the fix list. A window must not open before this — '
    'advance visibility is the requirement, not a nicety.';
COMMENT ON TABLE maintenance_window_items IS
    'The fix manifest for a window. Repair Bay appends as it decides; each row '
    'carries its own outcome so a close reports WHAT shipped, not just that it ended.';

COMMIT;
