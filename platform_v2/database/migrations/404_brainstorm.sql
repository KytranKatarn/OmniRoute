-- Migration 404: brainstorm_sessions + brainstorm_ideas
-- Supports T2069 — Brainstorm platform module (Option 3: durable, DB-backed, LCARS).
-- Per-user brainstorming sessions with clustered ideas, voting, and KB export.

CREATE TABLE IF NOT EXISTS brainstorm_sessions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(255) NOT NULL,
    goal        TEXT,
    status      VARCHAR(20)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived')),
    tags        TEXT[]       NOT NULL DEFAULT '{}',
    idea_count  INTEGER      NOT NULL DEFAULT 0,  -- denormalised counter, refreshed on idea CUD
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brainstorm_sessions_user
    ON brainstorm_sessions (user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS brainstorm_ideas (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER      NOT NULL REFERENCES brainstorm_sessions(id) ON DELETE CASCADE,
    content     TEXT         NOT NULL,
    cluster     VARCHAR(100),           -- optional group/theme label
    votes       INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brainstorm_ideas_session
    ON brainstorm_ideas (session_id, cluster, created_at);

COMMENT ON TABLE brainstorm_sessions IS
    'Brainstorm module (T2069) — per-user ideation sessions';
COMMENT ON TABLE brainstorm_ideas IS
    'Brainstorm module (T2069) — individual ideas within a session';
