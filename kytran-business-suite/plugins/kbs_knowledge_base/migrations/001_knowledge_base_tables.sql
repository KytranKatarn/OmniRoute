-- Knowledge Base plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

-- ---------------------------------------------------------------------------
-- Article categories
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    slug        VARCHAR(255) NOT NULL,
    description TEXT,
    parent_id   INTEGER REFERENCES kb_categories(id) ON DELETE SET NULL,
    sort_order  INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_categories_slug ON kb_categories (slug);

-- ---------------------------------------------------------------------------
-- Articles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_articles (
    id            SERIAL PRIMARY KEY,
    category_id   INTEGER REFERENCES kb_categories(id) ON DELETE SET NULL,
    title         VARCHAR(500) NOT NULL,
    slug          VARCHAR(500) NOT NULL,
    content       TEXT NOT NULL,
    excerpt       TEXT,
    status        VARCHAR(20) DEFAULT 'draft'
                      CHECK (status IN ('draft', 'published', 'archived')),
    author        VARCHAR(255),
    views         INTEGER DEFAULT 0,
    helpful_yes   INTEGER DEFAULT 0,
    helpful_no    INTEGER DEFAULT 0,
    tags          JSONB DEFAULT '[]',
    metadata      JSONB DEFAULT '{}',
    published_at  TIMESTAMP,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_articles_slug   ON kb_articles (slug);
CREATE INDEX IF NOT EXISTS idx_kb_articles_category      ON kb_articles (category_id);
CREATE INDEX IF NOT EXISTS idx_kb_articles_status        ON kb_articles (status);
CREATE INDEX IF NOT EXISTS idx_kb_articles_published     ON kb_articles (published_at);
