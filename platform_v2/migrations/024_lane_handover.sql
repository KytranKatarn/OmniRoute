-- Migration 024: Lane handover board (one shared handover for every coder lane)
-- Date: 2026-10-16
-- Purpose: Give codex / opencode / claude ONE place to record where they are and what
-- they are working on, so each lane (and the owner, in Dev HQ) can see the others.
-- Written through the MCP gateway (read_handover / update_handover) so a lane keeps
-- its handover current without leaving its session; surfaced on the Dev HQ "Lanes"
-- subtab of the consciousness module.
--
-- Idempotent: CREATE ... IF NOT EXISTS + ON CONFLICT, so re-running is safe.

CREATE TABLE IF NOT EXISTS lane_handover (
    lane        VARCHAR(32) PRIMARY KEY
                CHECK (lane IN ('opencode', 'codex', 'claude')),
    status      VARCHAR(24) NOT NULL DEFAULT 'idle'
                CHECK (status IN ('idle', 'working', 'blocked', 'reviewing', 'done')),
    headline    TEXT,
    working_on  TEXT,
    blockers    TEXT,
    next_step   TEXT,
    branch      VARCHAR(255),
    pr_url      TEXT,
    updated_by  VARCHAR(64),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  lane_handover            IS 'One row per coder lane: the shared handover board shown on the Dev HQ Lanes subtab.';
COMMENT ON COLUMN lane_handover.status     IS 'idle | working | blocked | reviewing | done';
COMMENT ON COLUMN lane_handover.working_on IS 'What this lane is doing right now (free text, one paragraph).';
COMMENT ON COLUMN lane_handover.blockers   IS 'Anything stopping this lane, or empty.';
COMMENT ON COLUMN lane_handover.next_step  IS 'The next concrete action when the lane resumes.';
COMMENT ON COLUMN lane_handover.updated_by IS 'Which process wrote this row (e.g. codex, opencode, owner).';

-- Append-only history, so a lane that wakes up can see how the others got here.
CREATE TABLE IF NOT EXISTS lane_handover_log (
    id          BIGSERIAL PRIMARY KEY,
    lane        VARCHAR(32) NOT NULL,
    status      VARCHAR(24),
    headline    TEXT,
    working_on  TEXT,
    blockers    TEXT,
    branch      VARCHAR(255),
    pr_url      TEXT,
    updated_by  VARCHAR(64),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lane_handover_log_lane
    ON lane_handover_log (lane, created_at DESC);

-- Seed one idle row per lane so the board renders before any lane has written to it.
INSERT INTO lane_handover (lane, status, headline, updated_by)
VALUES
    ('opencode', 'idle', 'No handover yet', 'migration'),
    ('codex',    'idle', 'No handover yet', 'migration'),
    ('claude',   'idle', 'No handover yet', 'migration')
ON CONFLICT (lane) DO NOTHING;

INSERT INTO schema_migrations (version) VALUES ('024') ON CONFLICT DO NOTHING;
