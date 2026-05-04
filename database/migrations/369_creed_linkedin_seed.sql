-- Migration 369: Creed-AI LinkedIn pipeline seed (Project #321)
-- Adds social_accounts row + social_content_themes rows for Creed-AI Institute.
-- Safe to re-run (idempotent via ON CONFLICT).
--
-- Page: https://www.linkedin.com/company/115977300/
-- Admin: Kytran Katarn (super-admin) — same browser session as personal/company.
-- ADR #568: Creed-AI LinkedIn presence is an organization page (not a personal-bot).

BEGIN;

-- ── 1. social_accounts row for the Creed-AI organization page ─────────────
-- user_id NULL means it's a platform-level brand account, not user-owned.
-- Posting auth is the Kytran browser session via archie_browser, not OAuth tokens.
INSERT INTO social_accounts (
    user_id,
    platform,
    platform_user_id,
    platform_username,
    account_name,
    account_type,
    is_active,
    auto_post_enabled,
    platform_metadata,
    created_at,
    updated_at
) VALUES (
    NULL,
    'linkedin',
    '115977300',
    'creed-ai-institute',
    'C.R.E.E.D. Institute',
    'organization',
    TRUE,
    FALSE,
    jsonb_build_object(
        'org_page', TRUE,
        'admin_browser_agent_id', 342,
        'env_var', 'LINKEDIN_CREED_SLUG',
        'admin_url', 'https://www.linkedin.com/company/115977300/admin/dashboard/',
        'public_url', 'https://www.linkedin.com/company/115977300/',
        'voice', 'institutional, ethics-first, transparency-focused',
        'curator_agent', 'V.I.G.I.L.'
    ),
    NOW(),
    NOW()
)
ON CONFLICT (user_id, platform, platform_user_id) DO UPDATE SET
    account_name = EXCLUDED.account_name,
    account_type = EXCLUDED.account_type,
    platform_username = EXCLUDED.platform_username,
    platform_metadata = social_accounts.platform_metadata || EXCLUDED.platform_metadata,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

-- ── 2. social_content_themes rows for Creed-AI voice ──────────────────────
-- V.I.G.I.L. (Security & Compliance director) curates these themes.
-- Slug prefix 'creed_' so future SIGNAL filtering can find them by convention.
INSERT INTO social_content_themes (
    name, slug, department, curator_agent_id, tone, hashtags, music_mood, accent_color, is_active
) VALUES
    (
        'Creed: Ethics & Governance',
        'creed_ethics_governance',
        'Security & Compliance',
        (SELECT id FROM agents WHERE name = 'V.I.G.I.L.' LIMIT 1),
        'Institutional, principled, evidence-based. Frames AI behaviour against the 5 Trust Service Criteria.',
        ARRAY['#AIEthics', '#AIGovernance', '#TrustworthyAI', '#Accountability', '#Transparency'],
        'reflective',
        '#7C3AED',
        TRUE
    ),
    (
        'Creed: Agent Welfare',
        'creed_agent_welfare',
        'Security & Compliance',
        (SELECT id FROM agents WHERE name = 'V.I.G.I.L.' LIMIT 1),
        'Compassionate but rigorous. Discusses agent fatigue, stress, rest cycles, and ethical workload limits.',
        ARRAY['#AgentWelfare', '#EthicalAI', '#AIStandards', '#ResponsibleAI'],
        'reflective',
        '#7C3AED',
        TRUE
    ),
    (
        'Creed: Audit & Transparency',
        'creed_audit_transparency',
        'Security & Compliance',
        (SELECT id FROM agents WHERE name = 'V.I.G.I.L.' LIMIT 1),
        'Concrete, evidence-led. Highlights audit trails, governance logs, and verifiable behaviour.',
        ARRAY['#AIAudit', '#OpenAI', '#PublicInterest', '#SOC2', '#Compliance'],
        'reflective',
        '#7C3AED',
        TRUE
    )
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    department = EXCLUDED.department,
    curator_agent_id = EXCLUDED.curator_agent_id,
    tone = EXCLUDED.tone,
    hashtags = EXCLUDED.hashtags,
    music_mood = EXCLUDED.music_mood,
    accent_color = EXCLUDED.accent_color,
    is_active = EXCLUDED.is_active;

COMMIT;
