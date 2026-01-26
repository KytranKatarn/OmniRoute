-- ============================================================================
-- Migration 019: Social Media Tables
-- Purpose: Social media command center for multi-platform management
-- Created: 2026-01-17
-- ============================================================================

-- Platform accounts (connected social media accounts)
CREATE TABLE IF NOT EXISTS social_accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    platform VARCHAR(50) NOT NULL, -- 'facebook', 'instagram', 'tiktok', 'twitter', 'linkedin', 'youtube', 'pinterest'
    platform_user_id VARCHAR(255), -- User ID on the platform
    platform_username VARCHAR(255), -- Username/handle
    account_name VARCHAR(255), -- Display name
    account_type VARCHAR(50) DEFAULT 'profile', -- 'profile', 'page', 'business', 'channel'

    -- OAuth tokens (encrypted in production)
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMP,

    -- Account details
    profile_image_url TEXT,
    followers_count INTEGER DEFAULT 0,
    following_count INTEGER DEFAULT 0,
    posts_count INTEGER DEFAULT 0,

    -- Settings
    is_active BOOLEAN DEFAULT TRUE,
    auto_post_enabled BOOLEAN DEFAULT FALSE,
    optimal_posting_times JSONB DEFAULT '[]', -- Array of best times to post

    -- Metadata
    last_sync_at TIMESTAMP,
    platform_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(user_id, platform, platform_user_id)
);

-- Social posts (content for posting)
CREATE TABLE IF NOT EXISTS social_posts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),

    -- Content
    content TEXT NOT NULL,
    media_urls JSONB DEFAULT '[]', -- Array of media URLs
    media_type VARCHAR(50), -- 'image', 'video', 'carousel', 'story', 'reel'
    hashtags TEXT[], -- Array of hashtags
    mentions TEXT[], -- Array of @mentions
    link_url TEXT, -- Link to include
    link_preview JSONB, -- Link preview data

    -- Targeting
    target_platforms TEXT[] DEFAULT '{}', -- Platforms to post to
    platform_specific_content JSONB DEFAULT '{}', -- Platform-specific variations

    -- Scheduling
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'scheduled', 'queued', 'publishing', 'published', 'failed', 'cancelled'
    scheduled_at TIMESTAMP,
    published_at TIMESTAMP,

    -- Campaign/Organization
    campaign_id INTEGER,
    category VARCHAR(100),
    tags TEXT[],

    -- AI Assistance
    ai_generated BOOLEAN DEFAULT FALSE,
    ai_suggestions JSONB DEFAULT '{}',

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Post results (actual posts per platform)
CREATE TABLE IF NOT EXISTS social_post_results (
    id SERIAL PRIMARY KEY,
    post_id INTEGER REFERENCES social_posts(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES social_accounts(id),
    platform VARCHAR(50) NOT NULL,

    -- Platform post details
    platform_post_id VARCHAR(255), -- ID of the post on the platform
    platform_post_url TEXT, -- Direct link to the post

    -- Status
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'published', 'failed'
    error_message TEXT,
    published_at TIMESTAMP,

    -- Engagement metrics (updated via sync)
    likes_count INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    shares_count INTEGER DEFAULT 0,
    saves_count INTEGER DEFAULT 0,
    views_count INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    engagement_rate DECIMAL(5,2) DEFAULT 0,

    -- Metadata
    platform_response JSONB DEFAULT '{}',
    last_metrics_sync TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Posting queue (for scheduled/auto posts)
CREATE TABLE IF NOT EXISTS social_media_queue (
    id SERIAL PRIMARY KEY,
    post_id INTEGER REFERENCES social_posts(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES social_accounts(id),

    -- Queue details
    priority INTEGER DEFAULT 5, -- 1-10, lower = higher priority
    scheduled_time TIMESTAMP NOT NULL,
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed', 'cancelled'

    -- Retry handling
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    last_attempt_at TIMESTAMP,
    next_retry_at TIMESTAMP,
    error_message TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Content templates (reusable post templates)
CREATE TABLE IF NOT EXISTS social_templates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Template content
    content_template TEXT NOT NULL, -- Supports {{variables}}
    media_urls JSONB DEFAULT '[]',
    default_hashtags TEXT[],

    -- Categorization
    category VARCHAR(100),
    platforms TEXT[], -- Recommended platforms
    post_type VARCHAR(50), -- 'promotional', 'educational', 'engagement', 'announcement'

    -- Usage stats
    times_used INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    -- Settings
    is_active BOOLEAN DEFAULT TRUE,
    is_ai_generated BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Analytics snapshots (aggregated metrics over time)
CREATE TABLE IF NOT EXISTS social_analytics (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES social_accounts(id),
    snapshot_date DATE NOT NULL,

    -- Follower metrics
    followers_count INTEGER DEFAULT 0,
    followers_gained INTEGER DEFAULT 0,
    followers_lost INTEGER DEFAULT 0,
    following_count INTEGER DEFAULT 0,

    -- Content metrics
    posts_count INTEGER DEFAULT 0,
    posts_published INTEGER DEFAULT 0,

    -- Engagement metrics
    total_likes INTEGER DEFAULT 0,
    total_comments INTEGER DEFAULT 0,
    total_shares INTEGER DEFAULT 0,
    total_saves INTEGER DEFAULT 0,
    total_views INTEGER DEFAULT 0,
    total_reach INTEGER DEFAULT 0,
    total_impressions INTEGER DEFAULT 0,

    -- Calculated metrics
    avg_engagement_rate DECIMAL(5,2) DEFAULT 0,
    best_posting_hour INTEGER, -- 0-23
    best_posting_day INTEGER, -- 0-6 (Sunday-Saturday)

    -- Raw data
    raw_metrics JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(account_id, snapshot_date)
);

-- Content calendar (visual calendar events)
CREATE TABLE IF NOT EXISTS social_calendar_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    post_id INTEGER REFERENCES social_posts(id),

    -- Event details
    title VARCHAR(255) NOT NULL,
    description TEXT,
    event_type VARCHAR(50) DEFAULT 'post', -- 'post', 'campaign_start', 'campaign_end', 'reminder', 'holiday'

    -- Timing
    event_date DATE NOT NULL,
    event_time TIME,
    all_day BOOLEAN DEFAULT FALSE,

    -- Visual
    color VARCHAR(20) DEFAULT '#6366f1',

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW()
);

-- Campaigns (group posts together)
CREATE TABLE IF NOT EXISTS social_campaigns (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Campaign period
    start_date DATE,
    end_date DATE,
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'active', 'paused', 'completed'

    -- Goals
    goal_type VARCHAR(50), -- 'awareness', 'engagement', 'traffic', 'conversions'
    target_reach INTEGER,
    target_engagement INTEGER,

    -- Results
    total_posts INTEGER DEFAULT 0,
    total_reach INTEGER DEFAULT 0,
    total_engagement INTEGER DEFAULT 0,

    -- Visual
    color VARCHAR(20) DEFAULT '#10b981',

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Media library (stored media for reuse)
CREATE TABLE IF NOT EXISTS social_media_library (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),

    -- File info
    filename VARCHAR(255) NOT NULL,
    file_url TEXT NOT NULL,
    file_type VARCHAR(50) NOT NULL, -- 'image', 'video', 'gif'
    file_size INTEGER, -- bytes
    mime_type VARCHAR(100),

    -- Dimensions
    width INTEGER,
    height INTEGER,
    duration INTEGER, -- seconds for video

    -- Metadata
    alt_text TEXT,
    tags TEXT[],
    folder VARCHAR(100),

    -- Usage
    times_used INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_social_accounts_user ON social_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_social_accounts_platform ON social_accounts(platform);
CREATE INDEX IF NOT EXISTS idx_social_posts_user ON social_posts(user_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_status ON social_posts(status);
CREATE INDEX IF NOT EXISTS idx_social_posts_scheduled ON social_posts(scheduled_at) WHERE status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_social_post_results_post ON social_post_results(post_id);
CREATE INDEX IF NOT EXISTS idx_social_queue_scheduled ON social_media_queue(scheduled_time) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_social_analytics_account_date ON social_analytics(account_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_social_calendar_date ON social_calendar_events(event_date);
CREATE INDEX IF NOT EXISTS idx_social_campaigns_status ON social_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_social_media_library_user ON social_media_library(user_id);

-- Insert sample platform configurations
INSERT INTO social_accounts (user_id, platform, platform_username, account_name, account_type, is_active, auto_post_enabled)
SELECT
    u.id,
    p.platform,
    'demo_' || p.platform,
    'Demo ' || p.display_name || ' Account',
    CASE p.platform
        WHEN 'youtube' THEN 'channel'
        WHEN 'facebook' THEN 'page'
        ELSE 'profile'
    END,
    FALSE, -- Not active until connected
    FALSE
FROM users u
CROSS JOIN (
    VALUES
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('twitter', 'Twitter/X'),
        ('linkedin', 'LinkedIn'),
        ('tiktok', 'TikTok'),
        ('youtube', 'YouTube'),
        ('pinterest', 'Pinterest')
) AS p(platform, display_name)
WHERE u.username = 'admin'
ON CONFLICT DO NOTHING;

-- Insert sample templates
INSERT INTO social_templates (user_id, name, description, content_template, category, platforms, post_type) VALUES
(
    (SELECT id FROM users WHERE username = 'admin' LIMIT 1),
    'Product Launch',
    'Announce a new product or feature',
    E'Introducing {{product_name}}!\n\n{{description}}\n\nLearn more: {{link}}\n\n#NewProduct #Launch #{{brand}}',
    'Marketing',
    ARRAY['facebook', 'instagram', 'twitter', 'linkedin'],
    'promotional'
),
(
    (SELECT id FROM users WHERE username = 'admin' LIMIT 1),
    'Weekly Tip',
    'Share a helpful tip with your audience',
    E'Tip of the Week\n\n{{tip_content}}\n\nDid you know this? Let us know in the comments!\n\n#Tips #{{topic}} #HelpfulAdvice',
    'Educational',
    ARRAY['facebook', 'instagram', 'twitter', 'linkedin'],
    'educational'
),
(
    (SELECT id FROM users WHERE username = 'admin' LIMIT 1),
    'Engagement Question',
    'Boost engagement with a question',
    E'{{question}}\n\nShare your thoughts in the comments!\n\n#Question #Community #ShareYourThoughts',
    'Engagement',
    ARRAY['facebook', 'instagram', 'twitter'],
    'engagement'
),
(
    (SELECT id FROM users WHERE username = 'admin' LIMIT 1),
    'Behind the Scenes',
    'Share a glimpse behind the scenes',
    E'Behind the Scenes\n\n{{content}}\n\nWant to see more? Let us know!\n\n#BehindTheScenes #{{brand}} #TeamLife',
    'Brand',
    ARRAY['instagram', 'tiktok', 'facebook'],
    'engagement'
)
ON CONFLICT DO NOTHING;

-- Grant permissions
GRANT ALL ON social_accounts TO archie;
GRANT ALL ON social_posts TO archie;
GRANT ALL ON social_post_results TO archie;
GRANT ALL ON social_media_queue TO archie;
GRANT ALL ON social_templates TO archie;
GRANT ALL ON social_analytics TO archie;
GRANT ALL ON social_calendar_events TO archie;
GRANT ALL ON social_campaigns TO archie;
GRANT ALL ON social_media_library TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE social_accounts IS 'Connected social media platform accounts';
COMMENT ON TABLE social_posts IS 'Social media posts (drafts, scheduled, published)';
COMMENT ON TABLE social_post_results IS 'Results of posts per platform with engagement metrics';
COMMENT ON TABLE social_media_queue IS 'Queue for scheduled and auto posts';
COMMENT ON TABLE social_templates IS 'Reusable content templates';
COMMENT ON TABLE social_analytics IS 'Daily analytics snapshots per account';
COMMENT ON TABLE social_calendar_events IS 'Content calendar events';
COMMENT ON TABLE social_campaigns IS 'Marketing campaigns grouping posts';
COMMENT ON TABLE social_media_library IS 'Media library for reusable content';
