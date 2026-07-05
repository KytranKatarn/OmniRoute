-- 449_email_reply_events.sql — per-human-agent reply SLA tracking (#3282)
-- Captures each human-agent reply with the time from the inbound message's received_at
-- to the reply's sent_at, so Email HQ can show per-agent response-time / reply-rate.
-- Forward-only: rows accrue from deploy (no historical reply-time data exists to backfill).
CREATE TABLE IF NOT EXISTS email_reply_events (
    id                    SERIAL PRIMARY KEY,
    source_message_id     INTEGER REFERENCES email_messages(id) ON DELETE SET NULL,  -- inbound msg replied to
    thread_id             INTEGER,        -- email_threads.id when known
    mailbox_id            INTEGER,        -- email_mailboxes.id the reply was sent FROM
    owner_agent_id        INTEGER,        -- the human agent that mailbox represents (email_mailboxes.owner_agent_id)
    sender_user_id        INTEGER,        -- users.id who actually sent it (COLLABORATOR)
    received_at           TIMESTAMPTZ,    -- inbound received_at (source), NULL if unmatched
    sent_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_time_seconds INTEGER,        -- sent_at - received_at (NULL if no source matched)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ere_owner_agent_sent ON email_reply_events(owner_agent_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_ere_mailbox_sent ON email_reply_events(mailbox_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_ere_source_msg ON email_reply_events(source_message_id);
