-- Browser Persona System -- Phase 1
-- Project #287

BEGIN;

-- browser_campaigns created first (FK referenced by agent_online_persona)
CREATE TABLE IF NOT EXISTS browser_campaigns (
    id                      SERIAL PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    description             TEXT,
    status                  VARCHAR(20) NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft','active','paused','completed')),
    campaign_type           VARCHAR(50),
    target_platforms        JSONB NOT NULL DEFAULT '[]',
    schedule                JSONB,
    content_brief           TEXT,
    participating_agent_ids JSONB NOT NULL DEFAULT '[]',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_browser_sessions (
    id                      SERIAL PRIMARY KEY,
    agent_id                INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    platform                VARCHAR(50) NOT NULL,
    username                VARCHAR(255),
    password_encrypted      TEXT,
    session_data_encrypted  TEXT,
    session_expires_at      TIMESTAMPTZ,
    status                  VARCHAR(20) NOT NULL DEFAULT 'missing'
                                CHECK (status IN ('missing','active','expired','error')),
    last_used_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, platform)
);

CREATE TABLE IF NOT EXISTS agent_online_persona (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER NOT NULL REFERENCES agents(id)
                            ON DELETE CASCADE UNIQUE,
    posting_frequency   VARCHAR(20) NOT NULL DEFAULT 'manual'
                            CHECK (posting_frequency IN ('daily','weekly','manual')),
    preferred_tone      VARCHAR(20) NOT NULL DEFAULT 'professional'
                            CHECK (preferred_tone IN ('professional','casual','bold')),
    active_platforms    JSONB NOT NULL DEFAULT '[]',
    topic_interests     JSONB NOT NULL DEFAULT '[]',
    engagement_rules    JSONB NOT NULL DEFAULT '{}',
    campaign_id         INTEGER REFERENCES browser_campaigns(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS browser_task_log (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill           VARCHAR(100) NOT NULL,
    platform        VARCHAR(50),
    params          JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','running','completed','failed')),
    result          JSONB,
    error_message   TEXT,
    screenshot_path TEXT,
    triggered_by    VARCHAR(50)
                        CHECK (triggered_by IN ('schedule','telegram','event','cli','api')),
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_browser_task_log_agent
    ON browser_task_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_browser_task_log_status
    ON browser_task_log(status);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_agent
    ON agent_browser_sessions(agent_id);

COMMIT;
