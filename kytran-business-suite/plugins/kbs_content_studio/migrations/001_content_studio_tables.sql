-- Content Studio plugin tables
-- Run inside the tenant schema (search_path already set by caller)

CREATE TABLE IF NOT EXISTS content_documents (
    id           SERIAL PRIMARY KEY,
    title        VARCHAR(255) NOT NULL,
    content      TEXT DEFAULT '',
    doc_type     VARCHAR(50)  DEFAULT 'article'
                 CHECK (doc_type IN ('article', 'blog', 'marketing', 'email', 'social', 'book', 'other')),
    status       VARCHAR(20)  DEFAULT 'draft'
                 CHECK (status IN ('draft', 'review', 'published', 'archived')),
    word_count   INT          DEFAULT 0,
    tags         JSONB        DEFAULT '[]',
    metadata     JSONB        DEFAULT '{}',
    created_at   TIMESTAMP    DEFAULT NOW(),
    updated_at   TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_templates (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    description      TEXT,
    doc_type         VARCHAR(50),
    template_content TEXT         DEFAULT '',
    is_active        BOOLEAN      DEFAULT TRUE,
    created_at       TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_documents_status     ON content_documents (status);
CREATE INDEX IF NOT EXISTS idx_content_documents_doc_type   ON content_documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_content_documents_created_at ON content_documents (created_at);
