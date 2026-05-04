-- 371_alternate_email_verifications.sql
-- Staging table for alternate-email ownership verifications.
-- The verified list lives in users.alternate_emails (text[]); this table
-- only holds in-flight tokens. SHA256-hashed; raw token never stored.
--
-- Spec: docs/superpowers/specs/2026-05-04-account-center-email-linking-design.md
-- Task: #2589 (Project #311)

BEGIN;

CREATE TABLE IF NOT EXISTS alternate_email_verifications (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alternate_email VARCHAR(255) NOT NULL,
    token_hash      VARCHAR(64) NOT NULL,
    expires_at      TIMESTAMP NOT NULL,
    used_at         TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alt_email_verif_token
    ON alternate_email_verifications(token_hash);
CREATE INDEX IF NOT EXISTS idx_alt_email_verif_user
    ON alternate_email_verifications(user_id);
CREATE INDEX IF NOT EXISTS idx_alt_email_verif_active
    ON alternate_email_verifications(user_id, alternate_email)
    WHERE used_at IS NULL;

COMMIT;
