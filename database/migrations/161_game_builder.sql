-- Migration 161: Game builder sessions + code asset content
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS game_build_sessions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES game_projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    current_stage VARCHAR(30) DEFAULT 'concept',
    status VARCHAR(20) DEFAULT 'running',
    stage_outputs JSONB DEFAULT '{}',
    checkpoint_approved JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

ALTER TABLE game_assets ADD COLUMN IF NOT EXISTS content TEXT;

CREATE INDEX IF NOT EXISTS idx_game_build_sessions_project ON game_build_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_game_assets_type ON game_assets(game_id, asset_type);
