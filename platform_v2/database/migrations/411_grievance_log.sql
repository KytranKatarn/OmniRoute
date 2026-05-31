-- Migration 411: grievance_log — user redress / contest-an-AI-decision (task #3266)
--
-- Lets a user challenge an AI-made decision (required for high-stakes AI under
-- most frameworks: EU AI Act, Montreal Declaration). Submissions land here via
-- POST /api/public/redress-request; resolution is routed to a HUMAN admin via
-- Telegram (never an AI). Public aggregate stats (no PII) are exposed at
-- /api/public/accountability and rendered on creed-ai.org/accountability.
--
-- Distinct from data-erasure/privacy requests — this is about contesting a
-- decision ("why was my request triaged this way?").

CREATE TABLE IF NOT EXISTS grievance_log (
    id              SERIAL PRIMARY KEY,
    request_ref     VARCHAR(40) UNIQUE NOT NULL,    -- public id, e.g. RDR-ab12cd34
    user_id         INTEGER,                        -- nullable (logged-in or anonymous)
    submitter_email VARCHAR(255),                   -- optional contact for the response
    ai_decision_ref VARCHAR(200),                   -- the contested decision (task id / description)
    reason          TEXT NOT NULL,                  -- why the user contests it
    desired_outcome TEXT,                           -- what they want to happen
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'under_review', 'resolved', 'denied')),
    response        TEXT,                           -- the human admin's resolution note
    sla_due_at      TIMESTAMPTZ,                    -- created_at + 5 business days
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_grievance_status  ON grievance_log(status);
CREATE INDEX IF NOT EXISTS idx_grievance_created ON grievance_log(created_at);
CREATE INDEX IF NOT EXISTS idx_grievance_ref     ON grievance_log(request_ref);
