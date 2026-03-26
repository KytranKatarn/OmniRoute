-- Social Media plugin tables
-- Run against the tenant schema (search_path already set by migration runner)

CREATE TABLE IF NOT EXISTS social_accounts (
    id               SERIAL PRIMARY KEY,
    platform         VARCHAR(50) NOT NULL CHECK (platform IN ('instagram','tiktok','facebook','twitter','linkedin','youtube')),
    account_name     VARCHAR(255) NOT NULL,
    account_id       VARCHAR(255),
    access_token     TEXT,
    refresh_token    TEXT,
    token_expires_at TIMESTAMP,
    is_active        BOOLEAN DEFAULT TRUE,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_posts (
    id               SERIAL PRIMARY KEY,
    account_id       INT REFERENCES social_accounts(id) ON DELETE SET NULL,
    content          TEXT NOT NULL,
    media_urls       JSONB DEFAULT '[]',
    status           VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft','scheduled','published','failed')),
    scheduled_at     TIMESTAMP,
    published_at     TIMESTAMP,
    platform_post_id VARCHAR(255),
    engagement       JSONB DEFAULT '{}',
    tags             JSONB DEFAULT '[]',
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_campaigns (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    status      VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft','active','paused','completed')),
    start_date  DATE,
    end_date    DATE,
    budget      DECIMAL(10,2),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_campaign_posts (
    id          SERIAL PRIMARY KEY,
    campaign_id INT NOT NULL REFERENCES social_campaigns(id) ON DELETE CASCADE,
    post_id     INT NOT NULL REFERENCES social_posts(id) ON DELETE CASCADE,
    UNIQUE (campaign_id, post_id)
);

CREATE TABLE IF NOT EXISTS social_analytics (
    id          SERIAL PRIMARY KEY,
    account_id  INT REFERENCES social_accounts(id) ON DELETE CASCADE,
    date        DATE NOT NULL,
    followers   INT DEFAULT 0,
    impressions INT DEFAULT 0,
    engagements INT DEFAULT 0,
    clicks      INT DEFAULT 0,
    metadata    JSONB DEFAULT '{}',
    UNIQUE (account_id, date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_social_posts_account_id  ON social_posts(account_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_status      ON social_posts(status);
CREATE INDEX IF NOT EXISTS idx_social_posts_scheduled   ON social_posts(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_social_campaigns_status  ON social_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_social_analytics_acct    ON social_analytics(account_id, date);
