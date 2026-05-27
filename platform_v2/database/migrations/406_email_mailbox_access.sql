-- Migration 406: Email mailbox scoped access — department column + grants table + user columns
-- Enables COLLABORATOR-role human agents to see only their department's mailboxes.

-- 1. Denormalised department on email_mailboxes (avoids repeated JOIN through agents on every request)
ALTER TABLE email_mailboxes ADD COLUMN IF NOT EXISTS department TEXT;

-- Backfill from agents table via owner_agent_id FK
UPDATE email_mailboxes m
SET department = a.department
FROM agents a
WHERE a.id = m.owner_agent_id
  AND m.department IS NULL;

-- 2. Explicit per-user mailbox grants (shared inboxes, cross-dept supervisors)
CREATE TABLE IF NOT EXISTS user_mailbox_grants (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mailbox_id  INTEGER NOT NULL REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    granted_by  INTEGER REFERENCES users(id),
    granted_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, mailbox_id)
);

-- 3. User columns for human agent accounts
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_department TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;
