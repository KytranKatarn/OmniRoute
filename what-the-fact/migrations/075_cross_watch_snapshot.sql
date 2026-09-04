-- 075_cross_watch_snapshot.sql — precomputed /cross-watch top-entities bundle (#6166)
--
-- WHY. /cross-watch measured >25s (client timeout) during the #6149 regression
-- sweeps. `_crosswatch_top()`'s ranking query — a full scan of shared.entity_mentions
-- (~2.15M rows after the #5799 backfill, an ~8x growth since the query was last
-- measured at "~670ms") joined to shared.entities per mention — now runs 5.47s
-- SOLO on an idle DB (measured 2026-09-04, EXPLAIN ANALYZE). It was already
-- cached, but `_CROSSWATCH_CACHE` is a plain in-process dict, and wtf-consumer
-- runs `gunicorn --workers 4 --max-requests`, so:
--   * 4 workers  => 4 independent caches => up to 4 requests pay full cost per TTL
--   * --max-requests recycles workers  => a recycled worker starts EMPTY, so the
--     5.47s+ path can recur instead of warming once
--   * Several concurrent cold workers running the SAME heavy scan against the
--     one hub DB (which also serves ingest, the other Watch products, and the
--     rest of WTF) is exactly the shape that turns a 5.47s solo query into a
--     >25s one under contention.
-- Same family as KB #282671 / migration 072 (activity_snapshot) — this is that
-- same fix, applied to the other in-process cache with the same failure shape.
--
-- One row, id=1. A snapshot has no history worth keeping: readers always want
-- the newest, and an unbounded log would need its own prune.

CREATE TABLE IF NOT EXISTS wtf.cross_watch_snapshot (
    id           smallint     PRIMARY KEY DEFAULT 1,
    bundle       jsonb        NOT NULL,
    computed_at  timestamptz  NOT NULL DEFAULT NOW(),
    duration_ms  integer,
    -- Refresher identity, so a stuck snapshot can be traced to a container.
    computed_by  text,
    CONSTRAINT cross_watch_snapshot_single_row CHECK (id = 1)
);

COMMENT ON TABLE  wtf.cross_watch_snapshot IS
  'Precomputed /cross-watch top-entities ranking (migration 075, #6166). '
  'Shared across all wtf-consumer gunicorn workers so a worker recycle or a '
  'cold cache on any one worker cannot force a re-run of the ~5.5s ranking '
  'scan; see consumer/cross_watch_snapshot.py.';
COMMENT ON COLUMN wtf.cross_watch_snapshot.computed_at IS
  'Age is checked in SQL against NOW() by the reader, not the caller''s local '
  'clock — the writer and reader are different containers/processes.';

-- wtfuser is the app role; new wtf tables MUST be granted or the app cannot
-- read them (the migration-047 lesson — apps do not connect as the owner).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, INSERT, UPDATE ON wtf.cross_watch_snapshot TO wtfuser;
    END IF;
END $$;
