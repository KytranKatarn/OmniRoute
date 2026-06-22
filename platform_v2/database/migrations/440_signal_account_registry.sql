-- 440 — S.I.G.N.A.L. account registry (scale phase Slice 4a, #signal-scale)
-- Generalize the 2 hand-wired LinkedIn accounts (post_type personal/terry/company/creed,
-- duplicated as _ACCOUNT_AGENT_ID / _ACCOUNT_BROWSER_ID / _ACCOUNT_LABEL literal dicts
-- across 5 services) into a role-aware registry on the already-existing-but-empty
-- agent_platform_accounts table, so ARCHIE becomes a 3rd major + a supporting-agent
-- engagement fleet can be added by DATA, not code.
--
-- Idempotent. The table is empty today, so the constraint changes are safe.

BEGIN;

-- 1) Role-aware registry columns (all additive / nullable or defaulted).
ALTER TABLE agent_platform_accounts
    ADD COLUMN IF NOT EXISTS account_key         varchar(64),   -- unique per platform: personal/terry/company/creed/archie/...
    ADD COLUMN IF NOT EXISTS role                varchar(32),   -- major_author | company_page | supporting_engagement
    ADD COLUMN IF NOT EXISTS post_type           varchar(64),   -- canonical post_type string fed to the publish handler
    ADD COLUMN IF NOT EXISTS browser_agent_id    integer,       -- agents row whose browser PROFILE this account posts through
    ADD COLUMN IF NOT EXISTS company_slug        varchar(128),  -- company-page slug (106863155 / 115977300) for page posts
    ADD COLUMN IF NOT EXISTS company_join_status varchar(32) DEFAULT 'n/a',  -- supporting agents: not_joined|pending|joined
    ADD COLUMN IF NOT EXISTS can_post            boolean DEFAULT true,       -- may author posts
    ADD COLUMN IF NOT EXISTS can_engage          boolean DEFAULT false,      -- may like/share/comment (supporting fleet)
    ADD COLUMN IF NOT EXISTS voice_key           varchar(64),   -- persona/voice hint key for generation
    ADD COLUMN IF NOT EXISTS engagement_targets  jsonb,         -- supporting agents: who/what to engage
    ADD COLUMN IF NOT EXISTS display_label       varchar(128),  -- 👤 Kytran Katarn / 🏢 Kytran Empowerment Inc.
    ADD COLUMN IF NOT EXISTS profile_established  boolean DEFAULT false,      -- browser profile is logged in (postable)
    -- Per-account IP FOOTPRINT (owner mandate): each agent registers + accesses its account
    -- from a fixed egress so it looks like a distinct real person in a region. NULL = hub-direct
    -- (the owner's region). Maps to a node_name in the existing S.C.O.U.T. egress fabric
    -- (node_socks SOCKS5 per outpost; proxy_selector.resolve_session_egress). The 3 majors
    -- (personal/terry/archie) + the pages that ride 342 SHARE the hub egress; each SUPPORTING
    -- agent later gets its OWN regional node (outpost-uk/singapore/lithuania/...).
    ADD COLUMN IF NOT EXISTS egress_pref         varchar(64);

-- 2) Relax the blocking UNIQUE(agent_id, platform): personal/company/creed all ride
--    agent 342 (one Kytran login, actor-switched), so 3 rows share (342,'linkedin').
ALTER TABLE agent_platform_accounts DROP CONSTRAINT IF EXISTS agent_platform_accounts_agent_id_platform_key;
-- email was NOT NULL for the table's prior (unused) purpose; actor-switched pages have no
-- own email, so make it optional.
ALTER TABLE agent_platform_accounts ALTER COLUMN email DROP NOT NULL;
-- account_type stays NOT NULL — give it a default so the registry seed is clean.
ALTER TABLE agent_platform_accounts ALTER COLUMN account_type SET DEFAULT 'registry';

-- 3) New identity key: one row per (platform, account_key). Uniqueness is INTENTIONALLY
--    composite (platform, account_key), NOT global on account_key alone — the same key
--    (e.g. 'personal') must be reusable across platforms (a LinkedIn 'personal' and a
--    future twitter/x 'personal' for the same agent are different accounts). A global
--    UNIQUE(account_key) would wrongly collapse those and break multi-platform support.
CREATE UNIQUE INDEX IF NOT EXISTS uq_apa_platform_account_key
    ON agent_platform_accounts (platform, account_key) WHERE account_key IS NOT NULL;

-- 4) Seed the 4 existing accounts + ARCHIE (3rd major). post_type strings preserved EXACTLY
--    so the resolver returns identical values to the hardcoded literals.
--    ARCHIE is REGISTERED but can_post=false / profile_established=false until the owner
--    does its one-time noVNC login (own LinkedIn account on its business email).
INSERT INTO agent_platform_accounts
    (account_key, platform, agent_id, browser_agent_id, role, post_type, company_slug,
     display_label, can_post, can_engage, profile_established, account_type, is_active, created_at)
VALUES
    ('personal', 'linkedin', 342, 342, 'major_author',  'personal', NULL,
        '👤 Kytran Katarn',            true,  false, true,  'major', true, NOW()),
    ('terry',    'linkedin', 377, 377, 'major_author',  'terry',    NULL,
        '👤 Terry Caetano',            true,  false, true,  'major', true, NOW()),
    ('company',  'linkedin', 342, 342, 'company_page',  'company',  '106863155',
        '🏢 Kytran Empowerment Inc.',  true,  false, true,  'page',  true, NOW()),
    ('creed',    'linkedin', 342, 342, 'company_page',  'creed',    '115977300',
        '⚖️ Creed-AI',                 true,  false, true,  'page',  true, NOW()),
    ('archie',   'linkedin', 2,   2,   'major_author',  'archie',   NULL,
        '🤖 A.R.C.H.I.E.',             false, false, false, 'major', true, NOW())
ON CONFLICT (platform, account_key) WHERE account_key IS NOT NULL
DO UPDATE SET
    agent_id = EXCLUDED.agent_id,
    browser_agent_id = EXCLUDED.browser_agent_id,
    role = EXCLUDED.role,
    post_type = EXCLUDED.post_type,
    company_slug = EXCLUDED.company_slug,
    display_label = EXCLUDED.display_label,
    account_type = EXCLUDED.account_type;

COMMIT;
