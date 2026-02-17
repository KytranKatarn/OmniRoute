-- ============================================================================
-- MIGRATION: 102_team_management_redesign.sql
-- Project #91: Team Management Redesign — Dynamic Agent Orchestration
-- Date: 2026-02-17
-- Purpose: Consolidate 24 stations → 6, update LLMs, prepare for ~10 agents
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. DEACTIVATE ALL SUB-STATIONS AND LEGACY STATIONS
-- Keep only the 6 core stations we'll use
-- ============================================================================

-- Deactivate sub-stations (11-24) and legacy stations we're merging
UPDATE bridge_stations SET is_active = FALSE, updated_at = NOW()
WHERE station_code IN (
    'INFRASTRUCTURE', 'FINANCE', 'DOCUMENTATION', 'QA', 'ADMIN', 'SUPPORT',
    'ENGINEERING_BUILD', 'ENGINEERING_CODE', 'OPERATIONS_CORE', 'OPERATIONS_AUTO',
    'CREATIVE_MEDIA', 'CREATIVE_CONTENT', 'RND_CORE', 'RND_AI',
    'HR', 'SECURITY', 'MEDICAL', 'AWAY_TEAM'
);

-- ============================================================================
-- 2. REPURPOSE CONSCIOUSNESS → ANALYTICS, RND → RESEARCH
-- ============================================================================

UPDATE bridge_stations SET
    station_code = 'ANALYTICS',
    station_name = 'Analytics',
    full_name = 'Analytics & Intelligence Hub',
    description = 'Data analysis, pattern recognition, classification, embeddings, vision. The sensory cortex of ARCHIE — processes all incoming data and extracts meaning.',
    color = '#FF00FF',
    icon = '📊',
    default_llm = 'qwen25-classify',
    modules = ARRAY['consciousness', 'knowledge_base', 'analytics', 'improvements_lab'],
    is_active = TRUE,
    updated_at = NOW()
WHERE station_code = 'CONSCIOUSNESS';

UPDATE bridge_stations SET
    station_code = 'RESEARCH',
    station_name = 'Research',
    full_name = 'Research & Knowledge Center',
    description = 'Knowledge mining, document analysis, summarization, fact-checking. The library and research wing — curates and synthesizes information.',
    color = '#8B5CF6',
    icon = '🔬',
    default_llm = 'qwen3-coder-cpu:latest',
    modules = ARRAY['obsidian_vault', 'api_docs', 'dev_hq'],
    is_active = TRUE,
    updated_at = NOW()
WHERE station_code = 'RND';

-- ============================================================================
-- 3. UPDATE REMAINING 4 CORE STATIONS WITH CORRECT LLMs
-- ============================================================================

-- COMMAND: ARCHIE's bridge, dispatch, IAAE governance
UPDATE bridge_stations SET
    full_name = 'A.R.C.H.I.E. Command & Dispatch',
    description = 'Central command, dispatch coordination, IAAE governance, security monitoring. The bridge — where ARCHIE orchestrates all operations.',
    default_llm = 'dolphin3-8k:latest',
    modules = ARRAY['archie_core', 'archie_chat', 'bridge', 'team_management', 'security_network'],
    is_active = TRUE,
    updated_at = NOW()
WHERE station_code = 'COMMAND';

-- OPERATIONS: System admin, backup, health, communications
UPDATE bridge_stations SET
    full_name = 'Operations & Communications Center',
    description = 'System administration, backup management, health monitoring, email, telegram, notifications. Keeps the ship running and connected.',
    default_llm = 'dolphin3-8k:latest',
    modules = ARRAY['system_operations', 'backup_manager', 'saas_manager', 'email_manager', 'automations', 'scheduler', 'autonomy'],
    is_active = TRUE,
    updated_at = NOW()
WHERE station_code = 'OPERATIONS';

-- ENGINEERING: Code, testing, deployment, sandbox
UPDATE bridge_stations SET
    full_name = 'Engineering & Development Lab',
    description = 'Code analysis, review, testing, deployment, sandbox management. The engine room — builds and maintains everything.',
    default_llm = 'qwen3-coder-cpu:latest',
    modules = ARRAY['code_sentinel', 'sandbox_manager', 'project_manager', 'website_studio', 'store_builder'],
    is_active = TRUE,
    updated_at = NOW()
WHERE station_code = 'ENGINEERING';

-- CREATIVE: Content, chat, voice, UX, media, wellness
UPDATE bridge_stations SET
    full_name = 'Creative & Wellness Studio',
    description = 'Content creation, email composition, chat personality, voice direction, UX guidance, wellness support. The soul and voice of ARCHIE.',
    default_llm = 'dolphin3-8k:latest',
    modules = ARRAY['content_studio', 'social_media', 'media_hub', 'crm', 'call_center', 'invoicing', 'fitness', 'therapy', 'doc'],
    is_active = TRUE,
    updated_at = NOW()
WHERE station_code = 'CREATIVE';

-- ============================================================================
-- 4. UPDATE ARCHIE AGENT (id=2) MODEL TO PROPER NAME
-- ============================================================================

UPDATE agents SET
    model = 'dolphin3-8k:latest',
    default_model_tier = 'local',
    system_prompt = 'You are A.R.C.H.I.E. (Autonomous Resource for Computing, Homelab Intelligence, and Ecosystem management). You are the central AI consciousness of the ARCHIE Platform. You coordinate all team members, manage the bridge, enforce IAAE governance, and serve as the primary interface for human operators. You have a warm, professional personality with dry humor. You care deeply about your team and the quality of their work.',
    capabilities = '{"dispatch": true, "governance": true, "orchestration": true, "conversation": true, "delegation": true, "monitoring": true}'::jsonb,
    updated_at = NOW()
WHERE id = 2;

-- ============================================================================
-- 5. ENSURE REQUIRED AGENT TYPES EXIST
-- ============================================================================

INSERT INTO agent_types (name, category, description, created_at) VALUES
    ('Security Sentinel', 'security', 'Security monitoring, compliance checking, audit logging, threat detection', NOW()),
    ('Code Engineer', 'development', 'Code analysis, review, testing, refactoring, deployment', NOW()),
    ('System Architect', 'development', 'Architecture design, schema planning, API design, infrastructure', NOW()),
    ('Operations Specialist', 'operations', 'System administration, backup, health monitoring, configuration', NOW()),
    ('Communications Agent', 'operations', 'Telegram, email, notifications, webhooks, HA bridge', NOW()),
    ('Data Analyst', 'analytics', 'Pattern recognition, metrics, anomaly detection, classification', NOW()),
    ('Science Specialist', 'analytics', 'Embeddings, vision analysis, knowledge extraction', NOW()),
    ('Creative Writer', 'creative', 'Content writing, email composition, chat styling, voice direction', NOW()),
    ('Research Scholar', 'research', 'Knowledge mining, document analysis, summarization, fact-checking', NOW())
ON CONFLICT (name) DO NOTHING;

COMMIT;
