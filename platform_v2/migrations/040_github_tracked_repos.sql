-- GitHub Tracked Repositories for Webhook Ingestion
-- Phase 1-3: Webhook endpoint + repo registry + incremental reindex

CREATE TABLE IF NOT EXISTS github_tracked_repos (
    id SERIAL PRIMARY KEY,
    owner VARCHAR(255) NOT NULL,
    repo VARCHAR(255) NOT NULL,
    branch VARCHAR(255) DEFAULT 'main',
    webhook_secret VARCHAR(255),          -- HMAC secret for verifying webhook payloads
    auto_ingest BOOLEAN DEFAULT true,     -- Whether to auto-ingest on push
    webhook_id BIGINT,                     -- GitHub webhook ID for management
    webhook_url TEXT,                      -- Full webhook URL registered with GitHub
    last_event_at TIMESTAMP WITH TIME ZONE,
    last_event_type VARCHAR(50),           -- push, pull_request, etc.
    last_sha VARCHAR(64),                  -- Last processed commit SHA
    last_processed_at TIMESTAMP WITH TIME ZONE,
    relevance_tags TEXT[],                 -- Tags for categorization (ai-research, etc.)
    is_ai_repo BOOLEAN DEFAULT false,      -- Whether part of top-100 AI repos
    priority INTEGER DEFAULT 5,            -- Processing priority (1-10)
    max_files INTEGER,                     -- Per-repo file limit override
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',   -- active, paused, archived, error
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (owner, repo)
);

CREATE INDEX IF NOT EXISTS idx_github_tracked_repos_owner_repo ON github_tracked_repos(owner, repo);
CREATE INDEX IF NOT EXISTS idx_github_tracked_repos_status ON github_tracked_repos(status);
CREATE INDEX IF NOT EXISTS idx_github_tracked_repos_ai_repo ON github_tracked_repos(is_ai_repo);
CREATE INDEX IF NOT EXISTS idx_github_tracked_repos_last_event ON github_tracked_repos(last_event_at);

-- Webhook event log for audit/replay
CREATE TABLE IF NOT EXISTS github_webhook_events (
    id BIGSERIAL PRIMARY KEY,
    tracked_repo_id INTEGER REFERENCES github_tracked_repos(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,       -- push, pull_request, etc.
    github_delivery_id VARCHAR(255),       -- X-GitHub-Delivery header
    payload JSONB NOT NULL,                -- Full webhook payload
    processed BOOLEAN DEFAULT false,
    processing_error TEXT,
    processed_at TIMESTAMP WITH TIME ZONE,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_github_webhook_events_repo ON github_webhook_events(tracked_repo_id);
CREATE INDEX IF NOT EXISTS idx_github_webhook_events_processed ON github_webhook_events(processed);
CREATE INDEX IF NOT EXISTS idx_github_webhook_events_delivery ON github_webhook_events(github_delivery_id);

-- Incremental reindex queue
CREATE TABLE IF NOT EXISTS github_reindex_queue (
    id BIGSERIAL PRIMARY KEY,
    tracked_repo_id INTEGER REFERENCES github_tracked_repos(id) ON DELETE CASCADE,
    trigger_type VARCHAR(50) NOT NULL,     -- webhook_push, manual, scheduled, webhook_pr
    trigger_payload JSONB,                 -- Webhook payload or manual params
    from_sha VARCHAR(64),                  -- Base commit for diff
    to_sha VARCHAR(64),                    -- Head commit for diff
    changed_files JSONB,                   -- List of changed files from GitHub compare API
    status VARCHAR(50) DEFAULT 'pending',  -- pending, processing, completed, failed
    error_message TEXT,
    files_processed INTEGER DEFAULT 0,
    files_total INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_github_reindex_queue_status ON github_reindex_queue(status);
CREATE INDEX IF NOT EXISTS idx_github_reindex_queue_repo ON github_reindex_queue(tracked_repo_id);
CREATE INDEX IF NOT EXISTS idx_github_reindex_queue_created ON github_reindex_queue(created_at);
