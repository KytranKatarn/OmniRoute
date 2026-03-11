-- Node-local schema for knowledge cache, projects, tasks, and contacts
-- Supports Phase 2: Local KB (#822) + Local Projects/CRM (#823)

-- ============================================================
-- Knowledge Cache (#822)
-- Stores a subset of hub knowledge_base entries locally.
-- Node can search these without hitting the hub every time.
-- ============================================================
CREATE TABLE IF NOT EXISTS node_knowledge_cache (
    id SERIAL PRIMARY KEY,
    hub_kb_id INTEGER NOT NULL UNIQUE,
    title TEXT,
    content TEXT,
    knowledge_type VARCHAR(50),
    category VARCHAR(100),
    tags TEXT[] DEFAULT '{}',
    importance_score NUMERIC(3,2) DEFAULT 0.5,
    source_type VARCHAR(50),
    synced_at TIMESTAMP DEFAULT NOW(),
    hub_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nkc_type ON node_knowledge_cache(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_nkc_category ON node_knowledge_cache(category);
CREATE INDEX IF NOT EXISTS idx_nkc_tags ON node_knowledge_cache USING GIN(tags);

-- ============================================================
-- Projects (#823)
-- Mirrors unified_projects from hub for local access.
-- ============================================================
CREATE TABLE IF NOT EXISTS node_projects (
    id SERIAL PRIMARY KEY,
    hub_project_id INTEGER NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100),
    description TEXT,
    status VARCHAR(50) DEFAULT 'planning',
    priority INTEGER DEFAULT 5,
    project_type VARCHAR(50),
    tags VARCHAR(100)[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    synced_at TIMESTAMP DEFAULT NOW(),
    hub_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_np_status ON node_projects(status);
CREATE INDEX IF NOT EXISTS idx_np_slug ON node_projects(slug);

-- ============================================================
-- Tasks (#823)
-- Mirrors unified_tasks from hub for local access.
-- ============================================================
CREATE TABLE IF NOT EXISTS node_tasks (
    id SERIAL PRIMARY KEY,
    hub_task_id INTEGER NOT NULL UNIQUE,
    hub_project_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    priority INTEGER DEFAULT 5,
    assigned_agent VARCHAR(100),
    tags VARCHAR(100)[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    synced_at TIMESTAMP DEFAULT NOW(),
    hub_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nt_status ON node_tasks(status);
CREATE INDEX IF NOT EXISTS idx_nt_project ON node_tasks(hub_project_id);
CREATE INDEX IF NOT EXISTS idx_nt_agent ON node_tasks(assigned_agent);

-- ============================================================
-- Contacts (CRM) (#823)
-- Local mirror of CRM contacts for node agents to reference.
-- ============================================================
CREATE TABLE IF NOT EXISTS node_contacts (
    id SERIAL PRIMARY KEY,
    hub_contact_id INTEGER NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    company VARCHAR(255),
    role VARCHAR(100),
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    synced_at TIMESTAMP DEFAULT NOW(),
    hub_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nc_name ON node_contacts(name);
CREATE INDEX IF NOT EXISTS idx_nc_company ON node_contacts(company);

-- ============================================================
-- Sync watermark — tracks last sync timestamp per type
-- so incremental syncs only pull changes since last sync.
-- ============================================================
CREATE TABLE IF NOT EXISTS node_sync_watermarks (
    sync_type VARCHAR(50) PRIMARY KEY,
    last_synced_at TIMESTAMP NOT NULL DEFAULT '1970-01-01',
    record_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed watermark entries
INSERT INTO node_sync_watermarks (sync_type) VALUES ('knowledge_sync')
    ON CONFLICT (sync_type) DO NOTHING;
INSERT INTO node_sync_watermarks (sync_type) VALUES ('project_sync')
    ON CONFLICT (sync_type) DO NOTHING;
INSERT INTO node_sync_watermarks (sync_type) VALUES ('task_sync')
    ON CONFLICT (sync_type) DO NOTHING;
INSERT INTO node_sync_watermarks (sync_type) VALUES ('contact_sync')
    ON CONFLICT (sync_type) DO NOTHING;
