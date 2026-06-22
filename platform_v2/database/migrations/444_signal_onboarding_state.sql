-- 444_signal_onboarding_state.sql  (S7-P6.5a)
--
-- Forward-only onboarding state machine columns on the S.I.G.N.A.L. account registry. A new
-- account walks created -> business_email_set -> credentials_stored -> profile_logged_in
-- (owner noVNC) -> company_joined (owner phone + 2FA) -> skills_enabled -> active before it
-- may post/engage. Dormant until platform_settings signal:onboarding_enabled. The 4 live
-- accounts are backfilled to 'active' so the column never strands a live poster.
--
-- Idempotent. Applied manually:
--   docker exec -i archie_database psql -U archie -d archie < 444_signal_onboarding_state.sql

BEGIN;

ALTER TABLE agent_platform_accounts
    ADD COLUMN IF NOT EXISTS onboarding_state         TEXT DEFAULT 'created',
    ADD COLUMN IF NOT EXISTS owner_gate_phone         TEXT,          -- encrypted (BROWSER_ENCRYPTION_KEY)
    ADD COLUMN IF NOT EXISTS owner_gate_2fa_code_sent BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS onboarded_at             TIMESTAMPTZ;

-- Live accounts are already fully onboarded — never strand a live poster mid-state.
UPDATE agent_platform_accounts
   SET onboarding_state = 'active'
 WHERE account_key IN ('personal', 'terry', 'company', 'creed')
   AND COALESCE(onboarding_state, '') <> 'active';

CREATE INDEX IF NOT EXISTS idx_apa_onboarding_state
    ON agent_platform_accounts (onboarding_state) WHERE onboarding_state <> 'active';
CREATE INDEX IF NOT EXISTS idx_apa_owner_gate_phone
    ON agent_platform_accounts (account_key) WHERE owner_gate_phone IS NOT NULL;

INSERT INTO schema_migrations (version, description)
SELECT 444, 'S.I.G.N.A.L. onboarding state machine columns (S7-P6.5a)'
WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = '444');

COMMIT;
