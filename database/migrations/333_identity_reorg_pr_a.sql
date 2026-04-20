-- Migration 333: Identity reorg — Pixel/ROSETTA/Marcus (Project #262 PR A)
--
-- Three related changes, atomic via BEGIN/COMMIT:
--
-- 1. Pixel (id=13): contractor+human persona → pure AI acronym agent P.I.X.E.L.
--    Mia Santos persona dissolved. Bio rewritten as platform visual-media AI.
--    Portrait nulled (queue regen — current face is Mia, not AI-style).
--
-- 2. ROSETTA (id=134): SPLIT into two records
--    - Existing record becomes pure AI R.O.S.E.T.T.A. (worker_type → ai,
--      clean display_name, AI-first translation bio). Portrait nulled.
--    - New record: human Amina Youssef, Senior Technical Translator.
--      Keeps the Syrian-refugee multilingual persona; avatar points to
--      amina_youssef.png (copy of the original rosetta.png — her face).
--
-- 3. Marcus Rivera (id=5): decommission; create new Kytran record
--    (Co-Founder & Platform Architect, Executive Office). Mysterious
--    silhouette SVG as placeholder portrait; real image uploaded later
--    via the agent profile modal.

BEGIN;

-- ============================================================================
-- 1. Pixel → P.I.X.E.L. (pure AI)
-- ============================================================================
UPDATE agents
SET
    worker_type = 'ai',
    name = 'P.I.X.E.L.',
    display_name = 'P.I.X.E.L.',
    acronym = 'P.I.X.E.L.',
    acronym_expansion = 'Procedural Imaging eXtension & Editing Lab',
    first_name = NULL,
    last_name = NULL,
    pronouns = NULL,
    email = NULL,
    title = 'Visual Media AI',
    bio = 'The platform''s dedicated visual-media AI — the sole agent with ComfyUI access for image generation across all 17 departments. P.I.X.E.L. handles portraits, UI mockups, social-video frames, generative art, and avatar creation on demand. Runs on a lightweight footprint and coordinates VRAM swaps with the Ollama fleet so GPU-heavy workloads never block inference. Every pixel is deliberate; the prompt is the product.',
    avatar_url = NULL,  -- queued for regen; current pixel.png is Mia's face
    updated_at = now()
WHERE id = 13;

-- ============================================================================
-- 2a. ROSETTA (id=134) → pure AI R.O.S.E.T.T.A.
-- ============================================================================
UPDATE agents
SET
    worker_type = 'ai',
    name = 'R.O.S.E.T.T.A.',
    display_name = 'R.O.S.E.T.T.A.',
    acronym = 'R.O.S.E.T.T.A.',
    -- Keep existing acronym_expansion: "Resilient Orchestrated Semantic Engine
    -- for Translation & Transliteration Automation"
    first_name = NULL,
    last_name = NULL,
    pronouns = NULL,
    email = NULL,
    title = 'Translation & Localization AI',
    bio = 'The platform''s translation and localization AI. Handles technical documentation across 8 languages including RTL scripts (Arabic, Hebrew), maintains the cross-agent translation memory, and ensures cultural adaptation goes beyond literal word-swaps. Reviews every new string the i18n scanner surfaces and enforces terminology consistency platform-wide. Built to keep the platform readable to anyone, anywhere.',
    avatar_url = NULL,  -- queued for AI-style regen
    updated_at = now()
WHERE id = 134;

-- ============================================================================
-- 2b. New human record: Amina Youssef
-- ============================================================================
INSERT INTO agents (
    name,
    display_name,
    first_name,
    last_name,
    pronouns,
    email,
    worker_type,
    department,
    floor,
    title,
    bio,
    avatar_url,
    status,
    shift_state,
    is_department_ai,
    model,
    tier
)
VALUES (
    'Amina',
    'Amina Youssef',
    'Amina',
    'Youssef',
    'she/her',
    'amina.youssef@kytranempowerment.com',
    'internal',
    'Documentation & Knowledge',
    'CREATIVE',
    'Senior Technical Translator — Cross-Script Specialist',
    'Amina Youssef arrived in Canada in 2016 as a Syrian refugee, landing in Fredericton, New Brunswick with her family during the coldest February on record. Within two years she had learned English — adding to her native Arabic, French, and Turkish — earned a diploma in Translation Studies from UNB, and was working as a court interpreter. She now speaks Arabic, French, English, Turkish, and German fluently, with working knowledge of Spanish, Farsi, and Inuktitut. At Kytran Empowerment she ensures technical documentation is not just translated but culturally adapted. She built the platform''s Arabic and RTL interface, reviewed all 8 language packs for cultural accuracy, and partners with R.O.S.E.T.T.A. on terminology governance. Off hours she volunteers with the Multicultural Association of Fredericton, tutors newcomer families in English, and is writing a children''s book in Arabic about a Syrian girl who discovers snow.',
    '/static/media/portraits/amina_youssef.png',
    'active',
    'active',
    FALSE,
    'none',   -- humans don't have an LLM model
    1
);

-- ============================================================================
-- 3a. Marcus Rivera (id=5) — decommission
-- ============================================================================
UPDATE agents
SET
    shift_state = 'decommissioned',
    status = 'inactive',
    updated_at = now()
WHERE id = 5;

-- ============================================================================
-- 3b. New human record: Kytran (Co-Founder)
-- ============================================================================
INSERT INTO agents (
    name,
    display_name,
    first_name,
    last_name,
    pronouns,
    worker_type,
    department,
    floor,
    title,
    bio,
    avatar_url,
    status,
    shift_state,
    is_department_ai,
    model,
    tier
)
VALUES (
    'Kytran',
    'Kytran',
    'Kytran',
    NULL,
    'they/them',
    'internal',
    'Executive Office',
    'BRIDGE',
    'Co-Founder & Platform Architect',
    'Co-Founder of Kytran Empowerment and architect of the A.R.C.H.I.E. platform. Identity kept intentionally private — the work speaks first. Public profile populates from verified sources (LinkedIn, press) as those integrations come online. Builds platforms because someone has to prove ethical AI is practical, not aspirational.',
    '/static/media/portraits/kytran.svg',
    'active',
    'active',
    FALSE,
    'none',
    1
);

-- ============================================================================
-- Assertions
-- ============================================================================

-- Pixel reclass
DO $$
DECLARE
    pixel_type text;
BEGIN
    SELECT worker_type INTO pixel_type FROM agents WHERE id = 13;
    ASSERT pixel_type = 'ai', 'Pixel reclass failed: worker_type=' || COALESCE(pixel_type,'NULL');
END $$;

-- ROSETTA reclass
DO $$
DECLARE
    r_type text;
BEGIN
    SELECT worker_type INTO r_type FROM agents WHERE id = 134;
    ASSERT r_type = 'ai', 'ROSETTA reclass failed: worker_type=' || COALESCE(r_type,'NULL');
END $$;

-- New Amina exists
DO $$
DECLARE
    amina_count int;
BEGIN
    SELECT COUNT(*) INTO amina_count FROM agents
        WHERE display_name = 'Amina Youssef' AND worker_type = 'internal';
    ASSERT amina_count = 1, 'Expected 1 new Amina human record, got ' || amina_count;
END $$;

-- Marcus decommissioned
DO $$
DECLARE
    marcus_state text;
BEGIN
    SELECT shift_state INTO marcus_state FROM agents WHERE id = 5;
    ASSERT marcus_state = 'decommissioned', 'Marcus decommission failed: shift_state=' || COALESCE(marcus_state,'NULL');
END $$;

-- Kytran exists
DO $$
DECLARE
    kytran_count int;
BEGIN
    SELECT COUNT(*) INTO kytran_count FROM agents
        WHERE display_name = 'Kytran' AND department = 'Executive Office' AND shift_state = 'active';
    ASSERT kytran_count = 1, 'Expected 1 active Kytran record, got ' || kytran_count;
END $$;

COMMIT;
