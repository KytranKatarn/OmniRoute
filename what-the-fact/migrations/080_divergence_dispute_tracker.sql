-- Migration 080: divergence "checkable fact in dispute" tracker (task #6524)
--
-- /divergence's primary framing moves from FR/EN coverage-language detection
-- (unaffected by this migration — _divergence_rows keeps reading en_count/
-- fr_count/bias_scores exactly as before, just demoted to a secondary tab)
-- to a political-lean "checkable fact in dispute" tracker, matching
-- design-handoff/wtf-divergence.js.
--
-- ── divergence_score (pure math, PRECOMPUTED — same reasoning as migration
-- 079's blindspot columns: ingest/cluster_metrics.py already reads every
-- cluster's articles in one short transaction; adding a live per-request
-- join here would repeat that work against a table this codebase has
-- already stalled a migration on once) ──
--
-- score = mean pairwise |band_index_i - band_index_j| over every article
-- pair in the cluster, band_index in {0=left,1=center-left,2=center,
-- 3=center-right,4=right} (ingest/bias.py._BANDS, same 5 bands migration 079
-- already uses), normalized /4*100. Computed from band COUNTS in closed form
-- (no need to enumerate article pairs):
--   score = round( sum_{i<j} |i-j| * count_i * count_j / total_pairs / 4 * 100 )
--
-- Needs the 5 individual band counts. Migration 079's lean_l/c/r_count
-- already FOLDS band0+1 -> l and band3+4 -> r for the blindspot signal — those
-- are UNCHANGED here. This adds the 2 missing sub-splits so the 5 raw counts
-- are all available: band0_count (left), band1_count (center-left),
-- band3_count (center-right), band4_count (right). band2 = lean_c_count
-- (already exists, is exactly the center band, no fold applied to it).
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS band0_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS band1_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS band3_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS band4_count integer NOT NULL DEFAULT 0;
ALTER TABLE wtf.story_clusters ADD COLUMN IF NOT EXISTS divergence_score integer;

ALTER TABLE wtf.story_clusters DROP CONSTRAINT IF EXISTS story_clusters_divergence_score_check;
ALTER TABLE wtf.story_clusters ADD CONSTRAINT story_clusters_divergence_score_check
    CHECK (divergence_score IS NULL OR divergence_score BETWEEN 0 AND 100);

-- ── wtf.cluster_disputes: the LLM-backed half (disputed_point + verdict).
-- NOT derivable from existing data — no table anywhere stores "what is this
-- cluster's dispute about." One row per cluster, written by
-- ingest/dispute_backlog_worker.py via V.E.R.I.F.Y. (hub /api/analyze,
-- task="dispute" — same agent + capability as factcheck's "deep_analysis"
-- task, just a cluster-scoped prompt instead of article-scoped).
--
-- disputed_point IS NULLABLE ON PURPOSE: NULL means V.E.R.I.F.Y. was asked
-- and judged "disagreement is on tone, not a checkable point" — an HONEST
-- non-dispute finding, not a missing-data gap. Distinguish "not yet asked"
-- (no row at all — the backlog worker's own NOT EXISTS filter) from "asked,
-- found nothing checkable" (a row exists, disputed_point IS NULL).
--
-- verdict is a SEPARATE, NEW vocabulary from wtf.fact_checks.verdict
-- (verified/mostly_true/mixed/disputed/unverifiable/descriptive_reporting)
-- — that enum answers "is this claim true"; this one answers "has this
-- dispute been resolved by a document" (contested/developing/established,
-- or NULL = "not yet checked" as its own real state, distinct from
-- is_opinion = "no document can ever settle this, don't score it").
CREATE TABLE IF NOT EXISTS wtf.cluster_disputes (
    id              serial PRIMARY KEY,
    cluster_id      integer NOT NULL UNIQUE REFERENCES wtf.story_clusters(id),
    disputed_point  text,
    verdict         character varying(16),
    is_opinion      boolean NOT NULL DEFAULT false,
    confidence      real,
    checker         character varying(32) NOT NULL DEFAULT 'V.E.R.I.F.Y.',
    generated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cluster_disputes_verdict_check
        CHECK (verdict IS NULL OR verdict IN ('contested', 'developing', 'established'))
);

-- Query shape this exists for: "clusters missing a dispute row, qualifying
-- for a dispute check" (the backlog worker's own NOT EXISTS filter joins
-- back to story_clusters on article_count/band spread — no dedicated index
-- needed here beyond the UNIQUE(cluster_id) above, which already gives the
-- NOT EXISTS lookup an index).
