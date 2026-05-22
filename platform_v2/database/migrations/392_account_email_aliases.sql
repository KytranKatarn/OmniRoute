-- Migration 392: Account email aliases (T23 — canonical identity hub)
-- Links alternate email addresses to a canonical user account.
-- Allows Kytran to log in with gmail OR corporate email and get the same
-- account_id in /oauth/userinfo, so downstream products can store account_id
-- instead of email and avoid profile fragmentation.

CREATE TABLE IF NOT EXISTS account_email_aliases (
    id                SERIAL PRIMARY KEY,
    canonical_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alias_email       TEXT    NOT NULL,
    verified          BOOLEAN NOT NULL DEFAULT FALSE,
    added_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One email can only be an alias of ONE canonical account
    UNIQUE (alias_email)
);

CREATE INDEX IF NOT EXISTS idx_aea_canonical ON account_email_aliases (canonical_user_id);
CREATE INDEX IF NOT EXISTS idx_aea_email     ON account_email_aliases (alias_email);

-- Pre-populate Kytran's known aliases (verified = true since owner set them)
-- id=4 is Kytran's canonical account (kytran@kytranempowerment.com / username=kytran)
INSERT INTO account_email_aliases (canonical_user_id, alias_email, verified, added_by)
SELECT 4, 'kytranempowerment@gmail.com', TRUE, 4
WHERE EXISTS (SELECT 1 FROM users WHERE id = 4)
  AND NOT EXISTS (SELECT 1 FROM account_email_aliases WHERE alias_email = 'kytranempowerment@gmail.com')
ON CONFLICT (alias_email) DO NOTHING;

INSERT INTO account_email_aliases (canonical_user_id, alias_email, verified, added_by)
SELECT 4, 'Kytran@KytranEmpowerment.com', TRUE, 4
WHERE EXISTS (SELECT 1 FROM users WHERE id = 4)
  AND NOT EXISTS (SELECT 1 FROM account_email_aliases WHERE alias_email = 'Kytran@KytranEmpowerment.com')
ON CONFLICT (alias_email) DO NOTHING;
