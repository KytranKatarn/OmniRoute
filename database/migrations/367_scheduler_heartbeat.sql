-- 367_scheduler_heartbeat.sql
-- Path C — APScheduler sidecar container heartbeat
--
-- The scheduler container writes a row here every 30s. HTTP routes that
-- previously read `current_app.config["AGENT_LOOP"].running` and
-- `["CONSCIOUSNESS_SCHEDULER"].running` (in-process objects) read this
-- table instead, since the scheduler now lives in a separate Docker
-- container and the platform process no longer holds the Python objects.
--
-- One row per scheduler instance, identified by hostname. Latest row
-- wins; rows older than 24h get pruned by the heartbeat job itself.

CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
    id            SERIAL PRIMARY KEY,
    hostname      VARCHAR(128) NOT NULL,
    ts            TIMESTAMP    NOT NULL DEFAULT now(),
    running       BOOLEAN      NOT NULL DEFAULT TRUE,
    jobs_total    INTEGER      NOT NULL DEFAULT 0,
    jobs_pending  INTEGER      NOT NULL DEFAULT 0,
    next_run_ts   TIMESTAMP,
    details       JSONB        NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_scheduler_heartbeat_ts
    ON scheduler_heartbeat (ts DESC);
CREATE INDEX IF NOT EXISTS idx_scheduler_heartbeat_hostname_ts
    ON scheduler_heartbeat (hostname, ts DESC);
