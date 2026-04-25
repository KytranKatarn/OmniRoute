-- SP2 #1874: per-cluster neutral summaries in 3 lengths
CREATE TABLE IF NOT EXISTS wtf.summaries (
    id          SERIAL PRIMARY KEY,
    cluster_id  INTEGER      NOT NULL UNIQUE REFERENCES wtf.story_clusters(id) ON DELETE CASCADE,
    headline    VARCHAR(256) NOT NULL,   -- 1 line
    brief       TEXT         NOT NULL,   -- 1 paragraph (~2-3 sentences)
    full_text   TEXT         NOT NULL,   -- 3 paragraphs
    summarizer  VARCHAR(32)  NOT NULL DEFAULT 'extractive-v1',
    article_ids JSONB        NOT NULL DEFAULT '[]',
    created_at  TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_summaries_cluster ON wtf.summaries (cluster_id);
