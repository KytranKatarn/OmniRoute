-- Migration 381: Per-account content calendar and themes
-- Adds account column to social_content_themes + social_content_calendar,
-- seeds KE Inc. themes, and assigns per-account calendar slots.
-- Personal: Mon/Wed/Fri 9AM | KE Inc.: Tue/Thu/Sat 10AM | Creed: Mon/Thu/Fri 1PM

-- ── 1. Schema ──────────────────────────────────────────────────────────────
ALTER TABLE social_content_themes
    ADD COLUMN IF NOT EXISTS account VARCHAR(20) NOT NULL DEFAULT 'personal';

ALTER TABLE social_content_calendar
    ADD COLUMN IF NOT EXISTS account VARCHAR(20) NOT NULL DEFAULT 'personal';

-- Index for fast account lookups
CREATE INDEX IF NOT EXISTS idx_sct_account ON social_content_themes(account);
CREATE INDEX IF NOT EXISTS idx_scc_account_day ON social_content_calendar(account, day_of_week);

-- ── 2. Assign existing themes to accounts ──────────────────────────────────
UPDATE social_content_themes SET account = 'personal'
    WHERE id IN (1,2,3,4,5,6,7,8,9);
UPDATE social_content_themes SET account = 'creed'
    WHERE id IN (10,11,12);

-- ── 3. Fix personal calendar slots (already exist, update themes + account) ─
-- Mon (0): Build & Innovate — forward-thinking, maker energy
UPDATE social_content_calendar
    SET account = 'personal', theme_id = 4, time_of_day = '09:00:00'
    WHERE day_of_week = 0 AND slot_order = 0;

-- Wed (2): Live the Dream — aspirational, personal, relatable
UPDATE social_content_calendar
    SET account = 'personal', theme_id = 9, time_of_day = '09:00:00'
    WHERE day_of_week = 2 AND slot_order = 0;

-- Fri (4): Faith & Strength — spiritual, hopeful
UPDATE social_content_calendar
    SET account = 'personal', theme_id = 1, time_of_day = '09:00:00'
    WHERE day_of_week = 4 AND slot_order = 0;

-- ── 4. KE Inc. themes (company brand voice) ────────────────────────────────
INSERT INTO social_content_themes
    (name, slug, department, tone, hashtags, music_mood, accent_color, account, is_active)
VALUES
(
    'Platform Intelligence',
    'platform-intelligence',
    'Engineering & Technology',
    'Forward-thinking, technical, builder energy. Share AI agent milestones, platform features, and '
    'technical achievements from the ARCHIE ecosystem. Make complex AI concepts accessible and exciting.',
    ARRAY['#AIAgents','#KytranEmpowerment','#BuildingInPublic','#TechInnovation','#AIInfrastructure'],
    'uplifting',
    '#3b82f6',
    'company',
    TRUE
),
(
    'Business Suite Spotlight',
    'business-suite-spotlight',
    'Marketing & Communications',
    'Practical, ROI-focused, efficiency-driven. Showcase KBS automation wins, productivity improvements, '
    'and how Canadian businesses leverage AI to compete. Real outcomes, not theory.',
    ARRAY['#BusinessAutomation','#KytranEmpowerment','#SmallBusiness','#KBS','#CanadianBusiness'],
    'professional',
    '#10b981',
    'company',
    TRUE
),
(
    'Community & Ecosystem',
    'community-ecosystem',
    'Marketing & Communications',
    'Warm, inclusive, collaborative. Spotlight partner integrations, open-source contributions, '
    'Canadian AI ecosystem stories, and community builders making an impact.',
    ARRAY['#AIEcosystem','#KytranEmpowerment','#CanadianTech','#Community','#OpenSource'],
    'ambient',
    '#f59e0b',
    'company',
    TRUE
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    tone = EXCLUDED.tone,
    hashtags = EXCLUDED.hashtags,
    account = EXCLUDED.account,
    is_active = EXCLUDED.is_active;

-- ── 5. KE Inc. calendar slots: Tue (1), Thu (3), Sat (6) at 10 AM ──────────
INSERT INTO social_content_calendar
    (day_of_week, slot_order, theme_id, time_of_day, platform, account, auto_generate, is_active)
VALUES
(
    1, 0,
    (SELECT id FROM social_content_themes WHERE slug = 'platform-intelligence'),
    '10:00:00', 'linkedin', 'company', TRUE, TRUE
),
(
    3, 0,
    (SELECT id FROM social_content_themes WHERE slug = 'business-suite-spotlight'),
    '10:00:00', 'linkedin', 'company', TRUE, TRUE
),
(
    6, 0,
    (SELECT id FROM social_content_themes WHERE slug = 'community-ecosystem'),
    '10:00:00', 'linkedin', 'company', TRUE, TRUE
)
ON CONFLICT (day_of_week, slot_order) DO UPDATE SET
    account    = EXCLUDED.account,
    theme_id   = EXCLUDED.theme_id,
    time_of_day = EXCLUDED.time_of_day;

-- ── 6. Creed calendar slots: Mon (0), Thu (3), Fri (4) at 1 PM ─────────────
-- slot_order=1 since Mon/Fri slot_order=0 is personal, Thu slot_order=0 is company
INSERT INTO social_content_calendar
    (day_of_week, slot_order, theme_id, time_of_day, platform, account, auto_generate, is_active)
VALUES
(
    0, 1,
    (SELECT id FROM social_content_themes WHERE slug = 'creed_ethics_governance'),
    '13:00:00', 'linkedin', 'creed', TRUE, TRUE
),
(
    3, 1,
    (SELECT id FROM social_content_themes WHERE slug = 'creed_agent_welfare'),
    '13:00:00', 'linkedin', 'creed', TRUE, TRUE
),
(
    4, 1,
    (SELECT id FROM social_content_themes WHERE slug = 'creed_audit_transparency'),
    '13:00:00', 'linkedin', 'creed', TRUE, TRUE
)
ON CONFLICT (day_of_week, slot_order) DO UPDATE SET
    account    = EXCLUDED.account,
    theme_id   = EXCLUDED.theme_id,
    time_of_day = EXCLUDED.time_of_day;
