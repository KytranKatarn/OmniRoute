-- 057_api_keys.sql — self-serve API keys for the public WTF API (task #2138).
--
-- Beta shape (owner decision 2026-08-19): keys are FREE and self-serve to any
-- SSO-authenticated user. They exist to give a caller an IDENTITY, so limits can
-- be per-caller instead of per-IP, and so a single abusive client can be revoked
-- without throttling a whole NAT. Paid tiers are a table change in
-- consumer/rate_policy.py PLANS, not a schema change — nothing here assumes free.
--
-- ⚠️ THE SECRET IS NEVER STORED. Only sha256(secret) lands in key_hash, and the
-- full key is shown to the user exactly once. A database leak therefore does not
-- hand over working credentials. key_prefix IS public and stored in clear — it is
-- the lookup handle and what the UI shows, so a user can identify and revoke a
-- key without ever seeing the secret again.
--
-- Revocation is a TIMESTAMP, not a DELETE: an abuse investigation needs to know a
-- key existed and when it stopped working. Rows are never removed by the app.

BEGIN;

CREATE TABLE IF NOT EXISTS wtf.api_keys (
    id             SERIAL PRIMARY KEY,
    key_prefix     TEXT        NOT NULL UNIQUE,     -- public handle, 12 chars
    key_hash       TEXT        NOT NULL,            -- sha256(secret); secret never stored
    owner_email    TEXT        NOT NULL,            -- SSO identity that minted it
    label          TEXT,                            -- user-supplied, e.g. "research script"
    plan           TEXT        NOT NULL DEFAULT 'keyed'
                   CHECK (plan IN ('keyed', 'paid')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at   TIMESTAMPTZ,
    request_count  BIGINT      NOT NULL DEFAULT 0,
    revoked_at     TIMESTAMPTZ                      -- NULL = active
);

-- Hot path: every authenticated API request looks a key up by prefix. Partial
-- index on active keys only — a revoked key must still be findable for audit via
-- the UNIQUE constraint, but never costs the hot path anything.
CREATE INDEX IF NOT EXISTS idx_api_keys_active_prefix
    ON wtf.api_keys (key_prefix) WHERE revoked_at IS NULL;

-- "show me my keys" on the account page
CREATE INDEX IF NOT EXISTS idx_api_keys_owner
    ON wtf.api_keys (owner_email, created_at DESC);

COMMENT ON TABLE  wtf.api_keys              IS 'Self-serve public API keys (#2138). Secret is never stored.';
COMMENT ON COLUMN wtf.api_keys.key_hash     IS 'sha256 of the secret half. Plain sha256 is correct: the secret is 256 bits of CSPRNG output, so there is no dictionary to stretch against.';
COMMENT ON COLUMN wtf.api_keys.key_prefix   IS 'Public lookup handle, shown in the UI. Safe to log.';
COMMENT ON COLUMN wtf.api_keys.revoked_at   IS 'Soft revoke. Rows are never deleted — an abuse review needs the history.';

-- ════════════════════════════════════════════════════════════════════════════
-- WTFUSER GRANTS (mirror 033 §4 / 034 §12). This migration is applied as
-- `archie`, so the new table is archie-owned and wtfuser gets NOTHING by
-- default. The consumer app connects as wtfuser; without these grants every key
-- operation fails with "permission denied". Idempotent; guarded so environments
-- without the role skip cleanly.
-- ════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, INSERT, UPDATE ON wtf.api_keys TO wtfuser;
        -- deliberately NO DELETE: revocation is an UPDATE of revoked_at, and the
        -- app must not be able to erase the audit trail.
        GRANT USAGE, SELECT ON SEQUENCE wtf.api_keys_id_seq TO wtfuser;
    END IF;
END$$;

COMMIT;
