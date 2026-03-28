BEGIN;

-- Agent social media profiles
CREATE TABLE IF NOT EXISTS agent_social_profiles (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    platform VARCHAR(30) NOT NULL,
    handle VARCHAR(100),
    profile_url VARCHAR(500),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_social_agent ON agent_social_profiles (agent_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_social_unique ON agent_social_profiles (agent_id, platform);

-- Agent content posts (generated + posted)
CREATE TABLE IF NOT EXISTS agent_content_posts (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    platform VARCHAR(30),
    content TEXT NOT NULL,
    media_urls JSONB DEFAULT '[]',
    post_type VARCHAR(30) DEFAULT 'update',
    status VARCHAR(20) DEFAULT 'draft',
    scheduled_at TIMESTAMP,
    posted_at TIMESTAMP,
    engagement_stats JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_posts_agent ON agent_content_posts (agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_posts_status ON agent_content_posts (status);

-- Add writing voice fields to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS writing_tone VARCHAR(50) DEFAULT 'professional';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS writing_style TEXT DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS social_topics JSONB DEFAULT '[]';

COMMIT;
