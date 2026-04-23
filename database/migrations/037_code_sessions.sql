BEGIN;

CREATE TABLE IF NOT EXISTS code_sessions (
    id               SERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    source           TEXT NOT NULL CHECK (source IN ('user', 'repair_bay', 'archie_auto')),
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'paused', 'completed', 'failed')),
    tier             INTEGER NOT NULL CHECK (tier IN (1, 2)), -- 1=auto-PR, 2=human review via Repair Bay
    project_id       INTEGER REFERENCES unified_projects(id),
    proposal_id      INTEGER,                -- soft ref to improvement_proposals.id (not FK-enforced)
    conversation_id  INTEGER,                -- soft ref to conversations.id (not FK-enforced)
    opencode_pid     INTEGER,                -- NULL when not running; cleared on terminate/complete
    created_by       TEXT NOT NULL CHECK (created_by IN ('archie', 'user')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    result_branch    TEXT,
    result_pr_url    TEXT
);

CREATE TABLE IF NOT EXISTS code_session_events (
    id               SERIAL PRIMARY KEY,
    session_id       INTEGER NOT NULL REFERENCES code_sessions(id) ON DELETE CASCADE,
    event_type       TEXT NOT NULL
                     CHECK (event_type IN ('message','diff','file_change','summary','terminal_raw','error')),
    content          JSONB NOT NULL,         -- shape varies by event_type: {text}, {diff_before,diff_after}, {path,summary}, {raw}, {text}
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_code_session_events_session_event
    ON code_session_events(session_id, event_type);

CREATE INDEX IF NOT EXISTS idx_code_sessions_status
    ON code_sessions(status);

CREATE INDEX IF NOT EXISTS idx_code_sessions_source
    ON code_sessions(source);

COMMIT;
