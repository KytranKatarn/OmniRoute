-- Social video content queue for Media Studio AutoShorts builder
CREATE TABLE IF NOT EXISTS social_video_queue (
    id SERIAL PRIMARY KEY,
    title TEXT,
    quote_text TEXT,
    audio_mode VARCHAR(20) DEFAULT 'music',
    platform VARCHAR(50) DEFAULT 'linkedin',
    status VARCHAR(20) DEFAULT 'draft',
    scheduled_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,
    thumbnail_path TEXT,
    media_ids INTEGER[],
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_svq_status ON social_video_queue(status);
CREATE INDEX IF NOT EXISTS idx_svq_scheduled ON social_video_queue(scheduled_at);
