-- ============================================================================
-- Migration 040: Creation Tools Tables (Game Studio & Content Studio)
-- Phase 43: Creation Tools Completion
-- Date: 2026-01-19
-- ============================================================================

-- ============================================================================
-- GAME STUDIO TABLES
-- ============================================================================

-- Game Projects Table
CREATE TABLE IF NOT EXISTS game_projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    engine_type VARCHAR(50) NOT NULL DEFAULT '2d',  -- 2d, 3d, visual-novel, rpg, puzzle
    template VARCHAR(50) DEFAULT 'blank',
    status VARCHAR(30) DEFAULT 'development',  -- development, testing, published
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    thumbnail_url TEXT,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Game Scenes Table
CREATE TABLE IF NOT EXISTS game_scenes (
    id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES game_projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    scene_order INTEGER DEFAULT 0,
    scene_data JSONB DEFAULT '{}',  -- Scene objects, layers, properties
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Game Assets Table
CREATE TABLE IF NOT EXISTS game_assets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id INTEGER REFERENCES game_projects(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    asset_type VARCHAR(50) NOT NULL,  -- sprite, sound, music, model, script
    file_path TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    thumbnail_url TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Game Objects Table (for scene editor)
CREATE TABLE IF NOT EXISTS game_objects (
    id SERIAL PRIMARY KEY,
    scene_id INTEGER NOT NULL REFERENCES game_scenes(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    object_type VARCHAR(50) NOT NULL,  -- sprite, collider, trigger, text, etc.
    position_x FLOAT DEFAULT 0,
    position_y FLOAT DEFAULT 0,
    position_z FLOAT DEFAULT 0,
    scale_x FLOAT DEFAULT 1,
    scale_y FLOAT DEFAULT 1,
    rotation FLOAT DEFAULT 0,
    properties JSONB DEFAULT '{}',
    asset_id INTEGER REFERENCES game_assets(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- CONTENT STUDIO TABLES
-- ============================================================================

-- Content Documents Table
CREATE TABLE IF NOT EXISTS content_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    doc_type VARCHAR(50) NOT NULL DEFAULT 'article',  -- book, article, blog, copy, script, other
    content TEXT,
    description TEXT,
    word_count INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'draft',  -- draft, review, published
    template_id INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Content Versions Table (for version history)
CREATE TABLE IF NOT EXISTS content_versions (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES content_documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content TEXT,
    word_count INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);

-- Content AI Generations Table (track AI-generated content)
CREATE TABLE IF NOT EXISTS content_ai_generations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES content_documents(id) ON DELETE SET NULL,
    content_type VARCHAR(50) NOT NULL,
    topic TEXT NOT NULL,
    tone VARCHAR(50),
    target_length VARCHAR(20),
    keywords TEXT,
    prompt TEXT,
    generated_content TEXT,
    model_used VARCHAR(100),
    tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Game Studio indexes
CREATE INDEX IF NOT EXISTS idx_game_projects_user ON game_projects(user_id);
CREATE INDEX IF NOT EXISTS idx_game_projects_status ON game_projects(status);
CREATE INDEX IF NOT EXISTS idx_game_scenes_game ON game_scenes(game_id);
CREATE INDEX IF NOT EXISTS idx_game_assets_user ON game_assets(user_id);
CREATE INDEX IF NOT EXISTS idx_game_assets_type ON game_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_game_objects_scene ON game_objects(scene_id);

-- Content Studio indexes
CREATE INDEX IF NOT EXISTS idx_content_documents_user ON content_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_content_documents_type ON content_documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_content_documents_status ON content_documents(status);
CREATE INDEX IF NOT EXISTS idx_content_versions_document ON content_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_content_ai_generations_user ON content_ai_generations(user_id);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE game_projects IS 'Game projects created in Game Studio';
COMMENT ON TABLE game_scenes IS 'Scenes within game projects';
COMMENT ON TABLE game_assets IS 'Assets (sprites, sounds, models) for games';
COMMENT ON TABLE game_objects IS 'Objects placed in game scenes';
COMMENT ON TABLE content_documents IS 'Documents created in Content Studio';
COMMENT ON TABLE content_versions IS 'Version history for content documents';
COMMENT ON TABLE content_ai_generations IS 'AI-generated content tracking';

-- ============================================================================
-- DONE
-- ============================================================================

SELECT 'Migration 040: Creation Tools tables created successfully' as result;
