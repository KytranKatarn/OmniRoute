-- 072_activity_snapshot.sql — precomputed /activity stats bundle
--
-- WHY. /activity measured 10,737ms cold vs ~850ms warm, byte-identical output
-- (8 samples: 10737, 896, 844, 870, 788, 10183, 894, 854). Not a slow page — a
-- cold-cache page. `_ACTIVITY_CACHE` is a plain in-process dict, and
-- wtf-consumer runs `gunicorn --workers 4 --max-requests 800`, so:
--   * 4 workers  => 4 independent caches => up to 4 visitors pay full cost per TTL
--   * --max-requests recycles workers  => a recycled worker starts EMPTY, so the
--     10s path RECURS forever; it never "warms up once"
-- Same family as KB #282671 (archie_platform --workers 4, in-memory dict).
--
-- Cost measured on the hub DB: the bundle is ~40 whole-table COUNTs (60ms for
-- articles, 421ms for bias_scores) plus a 1,634ms union COUNT over the event
-- union. That does not belong on a visitor's request path.
--
-- ⚠️ Estimates (reltuples) are deliberately NOT used. routes.py comments the
-- stats block "Transparency page: the one place a wrong count is worst" —
-- accuracy is the product requirement here. This table stores EXACT counts,
-- computed off the request path; it changes WHERE they are computed, not WHAT.
--
-- One row, id=1. A snapshot has no history worth keeping: readers always want
-- the newest, and an unbounded log would need its own prune (the tier that had
-- a policy but no pruner — see backup-manager.md). Upsert keeps it at one row.

CREATE TABLE IF NOT EXISTS wtf.activity_snapshot (
    id           smallint     PRIMARY KEY DEFAULT 1,
    bundle       jsonb        NOT NULL,
    computed_at  timestamptz  NOT NULL DEFAULT NOW(),
    duration_ms  integer,
    -- Refresher identity, so a stuck snapshot can be traced to a container.
    computed_by  text,
    CONSTRAINT activity_snapshot_single_row CHECK (id = 1)
);

COMMENT ON TABLE  wtf.activity_snapshot IS
  'Precomputed /activity stats bundle (migration 072). Written by the internal '
  'refresh endpoint on wtf-ingest-api, read by the public consumer. Counts are '
  'EXACT — see the accuracy note in the migration and in routes.py.';
COMMENT ON COLUMN wtf.activity_snapshot.computed_at IS
  'Surfaced on the page as "as of HH:MM". A transparency page states its '
  'staleness rather than implying live.';

-- wtfuser is the app role; new wtf tables MUST be granted or the app cannot read
-- them (the migration-047 lesson — apps do not connect as the owner).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, INSERT, UPDATE ON wtf.activity_snapshot TO wtfuser;
    END IF;
END $$;
