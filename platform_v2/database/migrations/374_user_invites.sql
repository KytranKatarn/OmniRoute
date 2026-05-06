-- Migration 374: Platform user invite system
-- Allows admin to invite collaborators/partners by email with a signed token

CREATE TABLE IF NOT EXISTS user_invites (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL,
    role        VARCHAR(20)  NOT NULL DEFAULT 'collaborator',
    subscription_tier VARCHAR(20) NOT NULL DEFAULT 'collaborator',
    invited_by  INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token       VARCHAR(128) NOT NULL UNIQUE,
    status      VARCHAR(20)  NOT NULL DEFAULT 'pending',
    message     TEXT,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMP    NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    accepted_at TIMESTAMP,
    accepted_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT user_invites_status_check CHECK (status IN ('pending','accepted','expired','revoked'))
);

CREATE INDEX IF NOT EXISTS idx_user_invites_token  ON user_invites(token);
CREATE INDEX IF NOT EXISTS idx_user_invites_email  ON user_invites(email);
CREATE INDEX IF NOT EXISTS idx_user_invites_status ON user_invites(status);

-- Add collaborator to subscription_tier check if not already present
-- (safe no-op if the constraint already covers it via open-ended check)
