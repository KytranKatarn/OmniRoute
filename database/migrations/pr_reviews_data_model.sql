-- PR Reviews data model (Project #247 Phase 1 / Task #1799)
-- Tracks open PRs polled from GitHub and their AI review state.

CREATE TABLE IF NOT EXISTS pr_reviews (
    id                  SERIAL PRIMARY KEY,
    pr_number           INTEGER NOT NULL,
    repo                VARCHAR(200) NOT NULL DEFAULT 'KytranKatarn/archie-platform',
    title               TEXT NOT NULL,
    author              VARCHAR(100),
    state               VARCHAR(20) NOT NULL DEFAULT 'open',
    base_branch         VARCHAR(200),
    head_branch         VARCHAR(200),
    diff_url            TEXT,
    additions           INTEGER,
    deletions           INTEGER,
    changed_files       INTEGER,
    review_status       VARCHAR(30) NOT NULL DEFAULT 'pending',
    ai_summary          TEXT,
    ai_review_at        TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_polled_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT pr_reviews_state_check
        CHECK (state IN ('open','closed','merged')),
    CONSTRAINT pr_reviews_review_status_check
        CHECK (review_status IN ('pending','in_progress','reviewed','skipped')),
    CONSTRAINT pr_reviews_pr_repo_unique UNIQUE (pr_number, repo)
);

CREATE INDEX IF NOT EXISTS idx_pr_reviews_review_status ON pr_reviews (review_status);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_state ON pr_reviews (state);
CREATE INDEX IF NOT EXISTS idx_pr_reviews_updated ON pr_reviews (updated_at DESC);
