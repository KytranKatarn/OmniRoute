-- Migration 149: Media Studio tables
-- Idempotent: uses IF NOT EXISTS / ON CONFLICT
-- Note: Drops legacy media_assets and old media_generation_queue (different schema)

DROP TABLE IF EXISTS media_assets CASCADE;
DROP TABLE IF EXISTS media_generation_queue CASCADE;

-- Core media library — every generated asset
CREATE TABLE IF NOT EXISTS media_library (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER,
    media_type VARCHAR(20) NOT NULL,
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    prompt TEXT,
    negative_prompt TEXT,
    model VARCHAR(100),
    provider VARCHAR(50),
    node_id INTEGER REFERENCES remote_nodes(id),
    seed BIGINT,
    width INTEGER,
    height INTEGER,
    duration_seconds DECIMAL(8,2),
    duration_ms INTEGER,
    cost DECIMAL(10,4) DEFAULT 0,
    is_favorite BOOLEAN DEFAULT false,
    is_deleted BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_library_owner ON media_library(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_library_type ON media_library(media_type);
CREATE INDEX IF NOT EXISTS idx_media_library_created ON media_library(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_library_not_deleted ON media_library(id) WHERE is_deleted = false;

-- Generation queue — job tracking (owner_id NOT NULL — queue jobs always have an owner)
CREATE TABLE IF NOT EXISTS media_generation_queue (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    bridge_job_id INTEGER REFERENCES bridge_jobs(id) ON DELETE SET NULL,
    params JSONB NOT NULL DEFAULT '{}',
    result_media_id INTEGER REFERENCES media_library(id),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_queue_status ON media_generation_queue(status);
CREATE INDEX IF NOT EXISTS idx_media_queue_owner ON media_generation_queue(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_queue_bridge_job ON media_generation_queue(bridge_job_id);

-- Agent portraits — face identity system (Layer 2 ready)
CREATE TABLE IF NOT EXISTS agent_portraits (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) UNIQUE,
    canonical_image_path TEXT,
    identity_prompt TEXT,
    face_seed BIGINT,
    ip_adapter_ref_path TEXT,
    style_tags JSONB DEFAULT '[]',
    approved BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Media assignments — maps media to UI locations
CREATE TABLE IF NOT EXISTS media_assignments (
    id SERIAL PRIMARY KEY,
    media_id INTEGER REFERENCES media_library(id),
    assignment_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(30) NOT NULL,
    target_id INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_assignments_target ON media_assignments(target_type, target_id, is_active);

-- Agent voices — voice identity system (Layer 4 ready)
CREATE TABLE IF NOT EXISTS agent_voices (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) UNIQUE,
    provider VARCHAR(50) NOT NULL,
    voice_id VARCHAR(100),
    voice_params JSONB DEFAULT '{}',
    sample_path TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
