-- Migration 365: dispatch_pending_queue
-- Centralized model-affinity dispatch queue for all agent requests.
-- All products (platform, KBS, WTF, Watch series, apps) enqueue work here.
-- Department HQ model_dispatch_worker drains the queue, routing to whichever
-- node/hub has the required model already warm. ADR-004.

CREATE TABLE IF NOT EXISTS dispatch_pending_queue (
    id                  SERIAL PRIMARY KEY,

    -- What to run
    capability          VARCHAR(100)    NOT NULL,
    model_needed        VARCHAR(150)    NOT NULL,  -- e.g. 'qwen2.5:7b', 'comfyui', 'nomic-embed-text'
    model_type          VARCHAR(30)     NOT NULL DEFAULT 'llama',
                        -- llama | comfyui | embedding | tts | vision
    prompt              TEXT,
    system_prompt       TEXT,
    json_mode           BOOLEAN         NOT NULL DEFAULT FALSE,
    images              JSONB,                     -- base64 images for vision tasks

    -- Who requested it
    agent_name          VARCHAR(100),              -- preferred/assigned agent
    agent_id            INTEGER         REFERENCES agents(id) ON DELETE SET NULL,
    module_id           VARCHAR(100),              -- platform module that originated request
    source_product      VARCHAR(100),
                        -- 'archie_platform' | 'kbs' | 'wtf' | 'gov_watch' | 'market_watch'
                        -- | 'legal_watch' | 'civic_watch' | 'media_hub' | 'kso' | 'creed'
    requested_by        VARCHAR(100),              -- agent name or user identifier
    user_id             INTEGER         REFERENCES users(id) ON DELETE SET NULL,

    -- Routing hints
    priority            INTEGER         NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    node_preference     INTEGER         REFERENCES remote_nodes(id) ON DELETE SET NULL,
    local_only          BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Lifecycle
    status              VARCHAR(20)     NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'done', 'failed', 'expired')),
    queued_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    claimed_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,               -- NULL = no expiry; set for time-sensitive work

    -- Result
    result_response     TEXT,
    result_tokens       INTEGER,
    result_node_id      INTEGER         REFERENCES remote_nodes(id) ON DELETE SET NULL,
    result_model_used   VARCHAR(150),
    error               TEXT,

    -- Callback (optional — caller provides what to do when done)
    callback_type       VARCHAR(50),               -- 'approval_queue' | 'webhook' | 'task_result' | NULL
    callback_data       JSONB,                     -- {approval_id, task_id, webhook_url, ...}

    -- Metadata
    metadata            JSONB
);

-- Worker reads queued tasks ordered by model affinity + priority
CREATE INDEX IF NOT EXISTS idx_dpq_status_model
    ON dispatch_pending_queue (status, model_needed, priority DESC, queued_at ASC);

-- Product analytics
CREATE INDEX IF NOT EXISTS idx_dpq_source_product
    ON dispatch_pending_queue (source_product, queued_at DESC);

-- Agent lookup
CREATE INDEX IF NOT EXISTS idx_dpq_agent
    ON dispatch_pending_queue (agent_id, status);

-- TTL cleanup
CREATE INDEX IF NOT EXISTS idx_dpq_expires
    ON dispatch_pending_queue (expires_at)
    WHERE expires_at IS NOT NULL AND status = 'queued';

COMMENT ON TABLE dispatch_pending_queue IS
    'Centralized model-affinity dispatch queue. All products enqueue agent work here. '
    'Department HQ model_dispatch_worker routes to hub or fleet nodes based on warm models. '
    'ADR-004 (2026-05-01).';
