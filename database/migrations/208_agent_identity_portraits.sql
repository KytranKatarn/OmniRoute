BEGIN;

-- Agent portrait prompts and generated images
CREATE TABLE IF NOT EXISTS agent_portraits (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    image_path VARCHAR(500),
    prompt TEXT NOT NULL,
    negative_prompt TEXT DEFAULT '',
    style VARCHAR(50) DEFAULT 'professional',
    is_primary BOOLEAN DEFAULT false,
    generation_status VARCHAR(20) DEFAULT 'pending',
    generated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_portraits_agent ON agent_portraits (agent_id);

-- Fix duplicate primaries before creating unique index
UPDATE agent_portraits SET is_primary = false
WHERE id NOT IN (
    SELECT DISTINCT ON (agent_id) id
    FROM agent_portraits
    WHERE is_primary = true
    ORDER BY agent_id, created_at DESC
) AND is_primary = true;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_portraits_primary ON agent_portraits (agent_id) WHERE is_primary = true;

-- Agent photo gallery (lifestyle/work photos for social media)
CREATE TABLE IF NOT EXISTS agent_photo_gallery (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    image_path VARCHAR(500),
    caption TEXT DEFAULT '',
    category VARCHAR(30) DEFAULT 'professional',
    prompt TEXT,
    generated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_gallery_agent ON agent_photo_gallery (agent_id);

-- Add identity fields to agents table if not exist
ALTER TABLE agents ADD COLUMN IF NOT EXISTS bio TEXT DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS gender VARCHAR(20);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS ethnicity VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS age_range VARCHAR(20);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS appearance_notes TEXT DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS portrait_prompt TEXT DEFAULT '';

COMMIT;
