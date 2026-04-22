-- media_hub_users: add columns needed for dual-mode auth (local + Kytran SSO).
-- Idempotent — safe to run more than once.
--
-- Local users: sso_sub=NULL, username+password_hash required.
-- SSO users:   sso_sub=<idp.sub>, username=<sso username>, password_hash=NULL.

BEGIN;

ALTER TABLE media_hub_users
    ALTER COLUMN password_hash DROP NOT NULL;

ALTER TABLE media_hub_users
    ADD COLUMN IF NOT EXISTS sso_sub       VARCHAR(255),
    ADD COLUMN IF NOT EXISTS email         VARCHAR(255),
    ADD COLUMN IF NOT EXISTS display_name  VARCHAR(128),
    ADD COLUMN IF NOT EXISTS role          VARCHAR(32),
    ADD COLUMN IF NOT EXISTS product_tiers JSONB;

-- sso_sub must be unique when present; allow multiple NULLs for local users.
CREATE UNIQUE INDEX IF NOT EXISTS media_hub_users_sso_sub_unique
    ON media_hub_users (sso_sub) WHERE sso_sub IS NOT NULL;

-- Either sso_sub is present, or password_hash is — never neither.
ALTER TABLE media_hub_users
    DROP CONSTRAINT IF EXISTS media_hub_users_auth_method_chk;
ALTER TABLE media_hub_users
    ADD CONSTRAINT media_hub_users_auth_method_chk
    CHECK (sso_sub IS NOT NULL OR password_hash IS NOT NULL);

COMMIT;
