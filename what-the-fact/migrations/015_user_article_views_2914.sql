-- 015_user_article_views_2914.sql
-- Per-user article-view tracking for #2914 Media Literacy Score.
-- One row per (user_email, article_id) — additional visits update viewed_at.
-- Privacy: only logged for signed-in users; anonymous viewers are not tracked.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS wtf.user_article_views (
    user_email    VARCHAR(200) NOT NULL,
    article_id    INTEGER NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    first_view_at TIMESTAMP DEFAULT NOW(),
    last_view_at  TIMESTAMP DEFAULT NOW(),
    view_count    INTEGER DEFAULT 1,
    PRIMARY KEY (user_email, article_id)
);

CREATE INDEX IF NOT EXISTS idx_user_views_user_recent
    ON wtf.user_article_views(user_email, last_view_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_views_article
    ON wtf.user_article_views(article_id);

COMMENT ON TABLE wtf.user_article_views IS
    'Personal reading history per signed-in user. Powers /literacy dashboard (#2914) — bias distribution + Media Literacy Score.';

COMMENT ON COLUMN wtf.user_article_views.view_count IS
    'Incremented on every visit. UPSERT pattern in consumer/routes.py:article().';
