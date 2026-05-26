-- T3166: Cluster work queue — unified pending table across all capability types.
--
-- Enables idle agents to pick up overflow work from any capability bucket via a
-- single SKIP LOCKED claim pattern, regardless of their home department.
-- Extends the V.E.R.I.F.Y./fact_check_backlog pattern platform-wide.
--
-- Lifecycle: pending → claimed → completed | failed (retry resets to pending)

CREATE TABLE IF NOT EXISTS cluster_work_queue (
    id              BIGSERIAL PRIMARY KEY,
    capability      VARCHAR(100) NOT NULL,
    payload         JSONB        NOT NULL DEFAULT '{}',
    priority        SMALLINT     NOT NULL DEFAULT 5
                        CHECK (priority BETWEEN 1 AND 10),
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'claimed', 'completed', 'failed')),
    source          VARCHAR(100),                        -- module/job that submitted this item
    claimed_by      INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    claimed_at      TIMESTAMPTZ,
    available_after TIMESTAMPTZ  NOT NULL DEFAULT NOW(), -- delay/retry back-off
    expires_at      TIMESTAMPTZ,                         -- hard TTL; NULL = no expiry
    attempts        SMALLINT     NOT NULL DEFAULT 0,
    max_attempts    SMALLINT     NOT NULL DEFAULT 3,
    result          JSONB,                               -- output from completed dispatch
    error_text      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Generic claim index: ORDER BY priority DESC, id ASC FOR UPDATE SKIP LOCKED
CREATE INDEX IF NOT EXISTS idx_cwq_claim
    ON cluster_work_queue (priority DESC, id ASC)
    WHERE status = 'pending';

-- Per-capability drain for targeted workers (fact_check_backlog, bias_analysis, etc.)
CREATE INDEX IF NOT EXISTS idx_cwq_capability_claim
    ON cluster_work_queue (capability, priority DESC, id ASC)
    WHERE status = 'pending';

-- available_after index for delayed/retry items
CREATE INDEX IF NOT EXISTS idx_cwq_available
    ON cluster_work_queue (available_after)
    WHERE status = 'pending';

-- TTL reaper
CREATE INDEX IF NOT EXISTS idx_cwq_expires
    ON cluster_work_queue (expires_at)
    WHERE expires_at IS NOT NULL AND status = 'pending';

-- Seed the global default config row if none exists.
-- Workers resolve config via cluster_orchestration_service.resolve_config().
INSERT INTO cluster_orchestration_config (scope)
SELECT 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM cluster_orchestration_config WHERE scope = 'global'
);
