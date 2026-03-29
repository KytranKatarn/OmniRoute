-- Website Builder migration 005 -- Code Mode support.
-- Adds website_files table for virtual filesystem and editor_mode to projects.
-- All statements are idempotent. Run inside tenant schema.

CREATE TABLE IF NOT EXISTS website_files (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES website_projects(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    content     TEXT,
    mime_type   TEXT DEFAULT 'text/plain',
    file_size   INTEGER DEFAULT 0,
    is_directory BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, path)
);

CREATE INDEX IF NOT EXISTS idx_website_files_project ON website_files(project_id);
CREATE INDEX IF NOT EXISTS idx_website_files_path ON website_files(project_id, path);

ALTER TABLE website_projects
    ADD COLUMN IF NOT EXISTS editor_mode TEXT DEFAULT 'visual';

-- Add check constraint idempotently
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'website_projects_editor_mode_check'
    ) THEN
        ALTER TABLE website_projects
            ADD CONSTRAINT website_projects_editor_mode_check
            CHECK (editor_mode IN ('visual', 'code'));
    END IF;
END $$;
