-- Website Builder plugin tables
-- Run against tenant schema (search_path must be set before executing)

CREATE TABLE IF NOT EXISTS website_projects (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    domain      VARCHAR(255),
    status      VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'building', 'published', 'archived')),
    template    VARCHAR(100),
    settings    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS website_pages (
    id              SERIAL PRIMARY KEY,
    project_id      INT NOT NULL REFERENCES website_projects(id) ON DELETE CASCADE,
    title           VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL,
    content         TEXT DEFAULT '',
    page_type       VARCHAR(50) DEFAULT 'page' CHECK (page_type IN ('page', 'home', 'about', 'contact', 'blog', 'landing', 'custom')),
    sort_order      INT DEFAULT 0,
    is_published    BOOLEAN DEFAULT FALSE,
    seo_title       VARCHAR(255),
    seo_description TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (project_id, slug)
);

CREATE TABLE IF NOT EXISTS website_deployments (
    id             SERIAL PRIMARY KEY,
    project_id     INT NOT NULL REFERENCES website_projects(id),
    deployment_url VARCHAR(500),
    status         VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'building', 'deployed', 'failed')),
    provider       VARCHAR(50) DEFAULT 'github',
    deploy_log     TEXT,
    created_at     TIMESTAMP DEFAULT NOW(),
    completed_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_website_pages_project ON website_pages(project_id);
CREATE INDEX IF NOT EXISTS idx_website_pages_slug ON website_pages(slug);
CREATE INDEX IF NOT EXISTS idx_website_deployments_project ON website_deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_website_deployments_status ON website_deployments(status);
