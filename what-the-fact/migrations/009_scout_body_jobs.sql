-- 009_scout_body_jobs.sql
-- Tracks S.C.O.U.T. web_scrape jobs dispatched to recover full article bodies
-- for Google-News-snippet articles. One row per attempt; status persists so the
-- backlog worker won't re-dispatch the same article twice in a window.

CREATE TABLE IF NOT EXISTS wtf.scout_body_jobs (
    id            SERIAL      PRIMARY KEY,
    article_id    INTEGER     NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    scout_job_id  INTEGER,    -- scout_jobs.id on the hub (NULL until cli-dispatch returns)
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending|completed|failed|timeout
    body_before   INTEGER,    -- char length before rescue
    body_after    INTEGER,    -- char length after rescue (NULL if failed)
    error         TEXT,
    created_at    TIMESTAMP   NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scout_body_jobs_article ON wtf.scout_body_jobs(article_id);
CREATE INDEX IF NOT EXISTS idx_scout_body_jobs_status  ON wtf.scout_body_jobs(status);
