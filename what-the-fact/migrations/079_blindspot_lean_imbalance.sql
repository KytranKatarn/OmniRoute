-- Migration 079: story_clusters political-lean blindspot columns (task #6524)
--
-- /blindspot moves from an outlet-COUNT silence signal (coverage_gap_score,
-- unaffected by this migration) to a political-LEAN coverage imbalance
-- signal: was this story covered by only one side of the spectrum?
--
-- Precomputed here (not queried live) for the same reason coverage_gap_score
-- and certainty_label already are: ingest/cluster_metrics.py's batch pass
-- already reads every article in a cluster in one short, lock-safe
-- transaction — adding a live per-article JOIN to this on every /blindspot
-- request would repeat work already being done nightly for a different
-- column, against a table this codebase has already stalled a migration on
-- once (see cluster_metrics.py's own docstring on the 27-minute transaction).
--
-- lean_l_count / lean_c_count / lean_r_count: count of articles in the
-- cluster whose OWN bias_scores.score bands as left/center-left (L),
-- center (C), or center-right/right (R) — using ingest/bias.py's existing
-- 5-band thresholds (-0.55/-0.15/0.25/0.65), not a new scale.
--
-- blindspot_side: 'L' or 'R' when the mockup's exact thresholds call a
-- lean-imbalance blindspot (ported verbatim from design-handoff/wtf-blindspot.js):
--   MIN_TOTAL=4   fewer articles than this, no pattern to call
--   MIN_SIDES=4   partisan (L+R) coverage needed before a side can be judged
--   MINOR_MAX=0.25  quiet side must be <= 25% of the two-sided (L+R) coverage
--   MIN_DIFF=3    and at least 3 articles behind in absolute terms
-- NULL when the cluster is too thin or balanced to call either way.

ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS lean_l_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS lean_c_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS lean_r_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS blindspot_side character varying(1);

ALTER TABLE wtf.story_clusters DROP CONSTRAINT IF EXISTS story_clusters_blindspot_side_check;
ALTER TABLE wtf.story_clusters ADD CONSTRAINT story_clusters_blindspot_side_check
    CHECK (blindspot_side IS NULL OR blindspot_side IN ('L', 'R'));

-- Query shape this exists for: "clusters where blindspot_side IS NOT NULL,
-- newest first" — same partial-index pattern as idx_articles_latest_verdict
-- (migration 078): index only the rows a filter will ever match.
CREATE INDEX IF NOT EXISTS idx_story_clusters_blindspot_side
    ON wtf.story_clusters (blindspot_side, latest_published_at DESC)
    WHERE blindspot_side IS NOT NULL;
