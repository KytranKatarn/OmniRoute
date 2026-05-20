-- Migration 029: Bias drift history + cluster coverage/certainty metrics
-- #3007 Bias Drift Tracker, #3010 Coverage Gap Score, #3012 Certainty Labeling

-- #3007: daily snapshots of outlet bias for drift tracking
CREATE TABLE IF NOT EXISTS wtf.outlet_bias_history (
    id            SERIAL PRIMARY KEY,
    source_id     INTEGER NOT NULL REFERENCES wtf.sources(id) ON DELETE CASCADE,
    avg_score     REAL    NOT NULL,
    band          VARCHAR(20) NOT NULL,
    article_count INTEGER NOT NULL,
    window_days   INTEGER NOT NULL DEFAULT 30,
    snapshot_date DATE    NOT NULL DEFAULT CURRENT_DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- one snapshot per source per day
CREATE UNIQUE INDEX IF NOT EXISTS outlet_bias_history_source_date_idx
    ON wtf.outlet_bias_history (source_id, snapshot_date);

-- #3010: how many distinct outlets covered a cluster
ALTER TABLE wtf.story_clusters
    ADD COLUMN IF NOT EXISTS source_count      INTEGER NOT NULL DEFAULT 0;

-- coverage_gap_score: 0.0 (one outlet) → 1.0 (all outlets covered it)
ALTER TABLE wtf.story_clusters
    ADD COLUMN IF NOT EXISTS coverage_gap_score REAL NOT NULL DEFAULT 0.0;

-- #3012: Established / Developing / Contested
ALTER TABLE wtf.story_clusters
    ADD COLUMN IF NOT EXISTS certainty_label VARCHAR(20) NOT NULL DEFAULT 'developing';

ALTER TABLE wtf.story_clusters
    ADD COLUMN IF NOT EXISTS metrics_updated_at TIMESTAMPTZ;
