-- T3279: email_push_events — cross-process SSE event bus for IMAP IDLE push.
-- IDLE workers (archie_scheduler) INSERT here; SSE stream endpoint (archie_platform)
-- polls this table every ~3 s and emits SSE events to connected browsers.

CREATE TABLE IF NOT EXISTS email_push_events (
    id         BIGSERIAL PRIMARY KEY,
    mailbox_id INTEGER   NOT NULL,
    count      INTEGER   NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_push_events_mailbox_id
    ON email_push_events (mailbox_id, id);

CREATE INDEX IF NOT EXISTS idx_email_push_events_created_at
    ON email_push_events (created_at);
