-- 033_journalist_entities.sql — entity-search indexes + journalist support.
-- Milestone A creates these objects (search indexes + journalist groundwork);
-- Milestone B populates wtf.article_author_tags. Idempotent + additive.
-- Apply to the hub `wtf` DB manually: psql -U archie -d wtf -f 033_journalist_entities.sql

-- 1. Allow journalist entities (030 CHECK was person|organization only)
ALTER TABLE shared.entities DROP CONSTRAINT IF EXISTS entities_entity_type_check;
ALTER TABLE shared.entities
    ADD CONSTRAINT entities_entity_type_check
    CHECK (entity_type IN ('person', 'organization', 'journalist'));

-- 2. WTF-local writer-tag mirror (parallels wtf.article_mp_tags; empty until Milestone B)
CREATE TABLE IF NOT EXISTS wtf.article_author_tags (
    id         SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    entity_id  INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    match_type VARCHAR(20) NOT NULL DEFAULT 'rss_author',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (article_id, entity_id)
);

-- 3. Search / group-by indexes
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity_ctype
    ON shared.entity_mentions (entity_id, content_type);
CREATE INDEX IF NOT EXISTS idx_entities_type_slug
    ON shared.entities (entity_type, slug);
CREATE INDEX IF NOT EXISTS idx_article_author_tags_entity
    ON wtf.article_author_tags (entity_id);
CREATE INDEX IF NOT EXISTS idx_article_author_tags_article
    ON wtf.article_author_tags (article_id);

-- 4. Grant the WTF app role (wtfuser) access to the new table + its sequence.
--    This migration is applied as `archie` (see header), so the table is archie-owned
--    and wtfuser gets NOTHING by default — unlike sibling wtf tables, which were created
--    by wtfuser and are owned by it. Without this, ingest byline-tagging fails with
--    "permission denied for table article_author_tags" (the hook is non-fatal, so it
--    silently captures nothing). Idempotent; guarded so envs without the role skip cleanly.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.article_author_tags TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE wtf.article_author_tags_id_seq TO wtfuser;
    END IF;
END $$;
