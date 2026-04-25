-- SP2 #1873: story clustering — group articles about the same event
CREATE TABLE IF NOT EXISTS wtf.story_clusters (
    id                    SERIAL PRIMARY KEY,
    representative_title  VARCHAR(1024) NOT NULL,
    earliest_published_at TIMESTAMP     NOT NULL,
    latest_published_at   TIMESTAMP     NOT NULL,
    article_count         INTEGER       NOT NULL DEFAULT 1,
    created_at            TIMESTAMP     NOT NULL DEFAULT now(),
    updated_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_story_clusters_latest ON wtf.story_clusters (latest_published_at DESC);

ALTER TABLE wtf.articles
    ADD COLUMN IF NOT EXISTS cluster_id INTEGER REFERENCES wtf.story_clusters(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_articles_cluster ON wtf.articles (cluster_id) WHERE cluster_id IS NOT NULL;
