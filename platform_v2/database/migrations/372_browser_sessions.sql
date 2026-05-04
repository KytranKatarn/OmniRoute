-- 372_browser_sessions.sql
-- Layer A — Browser Session Lifecycle Management.
-- DB-backed session storage replaces archie-browser's on-disk encrypted JSON.
-- Single source of truth queryable by probe job, reactive layer, DHQ UI.
--
-- Spec: docs/superpowers/specs/2026-05-04-browser-session-lifecycle-design.md
-- Plan: docs/superpowers/plans/2026-05-04-browser-session-lifecycle-day1.md

BEGIN;

CREATE TABLE IF NOT EXISTS browser_sessions (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    platform            VARCHAR(50) NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'unverified',
    encrypted_state     BYTEA,
    last_used_at        TIMESTAMP,
    last_probe_at       TIMESTAMP,
    last_probe_ok       BOOLEAN,
    last_failure_reason TEXT,
    reauth_token        VARCHAR(64),
    reauth_expires_at   TIMESTAMP,
    deferred_count      INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(agent_id, platform),
    CONSTRAINT browser_sessions_status_check CHECK (
        status IN ('unverified', 'active', 'stale', 'reauth_pending', 'reauth_active', 'disabled')
    )
);

CREATE INDEX IF NOT EXISTS idx_browser_sessions_status ON browser_sessions(status);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_probe ON browser_sessions(last_probe_at);

COMMIT;
