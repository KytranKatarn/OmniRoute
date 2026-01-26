-- Migration 047: Workload Rebalancing - 4 Module Max Per Station
-- Purpose: Split large stations into specialized sub-stations to enforce 4-module limit
-- Date: 2026-01-20
-- User Requirement: 4 modules max per agent

-- ============================================
-- STEP 1: Create new specialized stations
-- ============================================

-- ENGINEERING (9 modules) → Split into BUILD + CODE
INSERT INTO bridge_stations (station_code, station_name, description, modules, default_llm, color, position_order)
VALUES
    ('ENGINEERING_BUILD', 'Engineering - Build', 'Project creation and website building',
     ARRAY['project_builder', 'app_builder', 'website_builder', 'website_designer'],
     'deepseek-coder-v2:16b', '#0EA5E9', 6),
    ('ENGINEERING_CODE', 'Engineering - Code', 'Code editing, testing, and integration',
     ARRAY['code_editor', 'cursor_integration', 'testing_suite', 'game_studio'],
     'deepseek-coder-v2:16b', '#0EA5E9', 7)
ON CONFLICT (station_code) DO UPDATE SET
    modules = EXCLUDED.modules,
    description = EXCLUDED.description;

-- OPERATIONS (8 modules) → Split into CORE + AUTO
INSERT INTO bridge_stations (station_code, station_name, description, modules, default_llm, color, position_order)
VALUES
    ('OPERATIONS_CORE', 'Operations - Core', 'CRM, invoicing, scheduling, email',
     ARRAY['crm', 'invoicing', 'scheduler', 'email_manager'],
     'qwen2.5-coder:7b', '#FFAA00', 8),
    ('OPERATIONS_AUTO', 'Operations - Auto', 'Automations, workspace, planning',
     ARRAY['automations', 'google_workspace', 'task_planner', 'site_manager'],
     'qwen2.5-coder:7b', '#FFAA00', 9)
ON CONFLICT (station_code) DO UPDATE SET
    modules = EXCLUDED.modules,
    description = EXCLUDED.description;

-- CREATIVE (6 modules) → Split into MEDIA + CONTENT
INSERT INTO bridge_stations (station_code, station_name, description, modules, default_llm, color, position_order)
VALUES
    ('CREATIVE_MEDIA', 'Creative - Media', 'Images, video generation',
     ARRAY['media_studio', 'picture_generation', 'video_generation'],
     'dolphin3:latest', '#F472B6', 10),
    ('CREATIVE_CONTENT', 'Creative - Content', 'Content, social media, stories',
     ARRAY['content_studio', 'social_media', 'story_generation'],
     'dolphin3:latest', '#F472B6', 11)
ON CONFLICT (station_code) DO UPDATE SET
    modules = EXCLUDED.modules,
    description = EXCLUDED.description;

-- RND (6 modules) → Split into CORE + AI
INSERT INTO bridge_stations (station_code, station_name, description, modules, default_llm, color, position_order)
VALUES
    ('RND_CORE', 'R&D - Core', 'Blueprint, improvements, sandbox, code review',
     ARRAY['blueprint', 'improvements_lab', 'sandbox_manager', 'coderabbit'],
     'deepseek-coder:33b', '#8B5CF6', 12),
    ('RND_AI', 'R&D - AI', 'Fine-tuning and API documentation',
     ARRAY['fine_tuning', 'api_docs'],
     'deepseek-coder:33b', '#8B5CF6', 13)
ON CONFLICT (station_code) DO UPDATE SET
    modules = EXCLUDED.modules,
    description = EXCLUDED.description;

-- Move book_builder to DOCUMENTATION station
UPDATE bridge_stations
SET modules = array_append(modules, 'book_builder')
WHERE station_code = 'DOCUMENTATION'
  AND NOT ('book_builder' = ANY(modules));

-- ============================================
-- STEP 2: Reassign agents to new stations
-- ============================================

-- Get station IDs for reassignment
DO $$
DECLARE
    eng_build_id INTEGER;
    eng_code_id INTEGER;
    ops_core_id INTEGER;
    ops_auto_id INTEGER;
    creative_media_id INTEGER;
    creative_content_id INTEGER;
    rnd_core_id INTEGER;
    rnd_ai_id INTEGER;
    old_eng_id INTEGER;
    old_ops_id INTEGER;
    old_creative_id INTEGER;
    old_rnd_id INTEGER;
BEGIN
    -- Get new station IDs
    SELECT id INTO eng_build_id FROM bridge_stations WHERE station_code = 'ENGINEERING_BUILD';
    SELECT id INTO eng_code_id FROM bridge_stations WHERE station_code = 'ENGINEERING_CODE';
    SELECT id INTO ops_core_id FROM bridge_stations WHERE station_code = 'OPERATIONS_CORE';
    SELECT id INTO ops_auto_id FROM bridge_stations WHERE station_code = 'OPERATIONS_AUTO';
    SELECT id INTO creative_media_id FROM bridge_stations WHERE station_code = 'CREATIVE_MEDIA';
    SELECT id INTO creative_content_id FROM bridge_stations WHERE station_code = 'CREATIVE_CONTENT';
    SELECT id INTO rnd_core_id FROM bridge_stations WHERE station_code = 'RND_CORE';
    SELECT id INTO rnd_ai_id FROM bridge_stations WHERE station_code = 'RND_AI';

    -- Get old station IDs
    SELECT id INTO old_eng_id FROM bridge_stations WHERE station_code = 'ENGINEERING';
    SELECT id INTO old_ops_id FROM bridge_stations WHERE station_code = 'OPERATIONS';
    SELECT id INTO old_creative_id FROM bridge_stations WHERE station_code = 'CREATIVE';
    SELECT id INTO old_rnd_id FROM bridge_stations WHERE station_code = 'RND';

    -- ============================================
    -- ENGINEERING: Split 4 agents across 2 stations
    -- DevOps Engineer (Omar) → BUILD (primary)
    -- Morgan - Code Specialist → CODE (primary)
    -- CodeLlama Specialist → BUILD (backup)
    -- Dr. Alexis - Senior Developer → CODE (backup)
    -- ============================================

    -- DevOps Engineer (Omar Ibrahim) → ENGINEERING_BUILD as primary
    UPDATE station_assignments
    SET station_id = eng_build_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'DevOps Engineer')
      AND station_id = old_eng_id;

    -- Add Morgan to ENGINEERING_CODE as primary
    INSERT INTO station_assignments (station_id, agent_id, role_type, is_active)
    SELECT eng_code_id, id, 'primary', true FROM agents WHERE name = 'Morgan - Code Specialist'
    ON CONFLICT DO NOTHING;

    -- Update Morgan's old assignment to backup for BUILD
    UPDATE station_assignments
    SET station_id = eng_build_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Morgan - Code Specialist')
      AND station_id = old_eng_id;

    -- Add CodeLlama to ENGINEERING_BUILD as backup
    UPDATE station_assignments
    SET station_id = eng_build_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'CodeLlama Specialist')
      AND station_id = old_eng_id;

    -- Add Dr. Alexis to ENGINEERING_CODE as backup
    UPDATE station_assignments
    SET station_id = eng_code_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name LIKE 'Dr. Alexis%')
      AND station_id = old_eng_id;

    -- ============================================
    -- OPERATIONS: Split agents across 2 stations
    -- Operations Coordinator (Sarah) → CORE (primary)
    -- Operations Lead (Victoria) → AUTO (primary)
    -- Others → backup roles
    -- ============================================

    -- Operations Coordinator → OPERATIONS_CORE as primary
    UPDATE station_assignments
    SET station_id = ops_core_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Operations Coordinator')
      AND station_id = old_ops_id;

    -- Operations Lead → OPERATIONS_AUTO as primary
    UPDATE station_assignments
    SET station_id = ops_auto_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Operations Lead')
      AND station_id = old_ops_id;

    -- Project Manager → OPERATIONS_AUTO as backup
    UPDATE station_assignments
    SET station_id = ops_auto_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Project Manager')
      AND station_id = old_ops_id;

    -- Financial Analyst → OPERATIONS_CORE as backup
    UPDATE station_assignments
    SET station_id = ops_core_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Financial Analyst')
      AND station_id = old_ops_id;

    -- Sales agents → OPERATIONS_CORE as backup (CRM related)
    UPDATE station_assignments
    SET station_id = ops_core_id, role_type = 'backup'
    WHERE agent_id IN (SELECT id FROM agents WHERE name LIKE 'Sales Agent%' OR name = 'Account Manager')
      AND station_id = old_ops_id;

    -- Shipping → OPERATIONS_AUTO as backup
    UPDATE station_assignments
    SET station_id = ops_auto_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name LIKE 'Shipping%')
      AND station_id = old_ops_id;

    -- ============================================
    -- CREATIVE: Split agents across 2 stations
    -- Social Media Manager (Maya) → CONTENT (primary)
    -- Creative Content Innovator (Liam) → MEDIA (primary)
    -- Others → appropriate stations as backup
    -- ============================================

    -- Social Media Manager → CREATIVE_CONTENT as primary
    UPDATE station_assignments
    SET station_id = creative_content_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Social Media Manager')
      AND station_id = old_creative_id;

    -- Creative Content Innovator → CREATIVE_MEDIA as primary
    UPDATE station_assignments
    SET station_id = creative_media_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Creative Content Innovator')
      AND station_id = old_creative_id;

    -- Visual Content Specialist → CREATIVE_MEDIA as backup
    UPDATE station_assignments
    SET station_id = creative_media_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Visual Content Specialist')
      AND station_id = old_creative_id;

    -- Content Writer → CREATIVE_CONTENT as backup
    UPDATE station_assignments
    SET station_id = creative_content_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Content Writer')
      AND station_id = old_creative_id;

    -- Luna, Community Manager, Social Media Expert → CREATIVE_CONTENT as backup
    UPDATE station_assignments
    SET station_id = creative_content_id, role_type = 'backup'
    WHERE agent_id IN (SELECT id FROM agents WHERE name IN ('Luna - Creative Specialist', 'Community Manager', 'Social Media Expert'))
      AND station_id = old_creative_id;

    -- ============================================
    -- RND: Split agents across 2 stations
    -- Solutions Architect → CORE (primary)
    -- Product Manager → AI (primary)
    -- Code Reviewer → CORE (backup)
    -- ============================================

    -- Solutions Architect → RND_CORE as primary
    UPDATE station_assignments
    SET station_id = rnd_core_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Solutions Architect')
      AND station_id = old_rnd_id;

    -- Product Manager → RND_AI as primary
    UPDATE station_assignments
    SET station_id = rnd_ai_id, role_type = 'primary'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Product & Improvement Manager')
      AND station_id = old_rnd_id;

    -- Code Reviewer → RND_CORE as backup
    UPDATE station_assignments
    SET station_id = rnd_core_id, role_type = 'backup'
    WHERE agent_id = (SELECT id FROM agents WHERE name = 'Code Reviewer')
      AND station_id = old_rnd_id;

END $$;

-- ============================================
-- STEP 3: Disable old oversized stations
-- ============================================
UPDATE bridge_stations SET is_active = false WHERE station_code IN ('ENGINEERING', 'OPERATIONS', 'CREATIVE', 'RND');

-- ============================================
-- STEP 4: Update position order for new layout
-- ============================================
UPDATE bridge_stations SET position_order =
    CASE station_code
        WHEN 'COMMAND' THEN 1
        WHEN 'CONSCIOUSNESS' THEN 2
        WHEN 'HR' THEN 3
        WHEN 'RND_CORE' THEN 4
        WHEN 'RND_AI' THEN 5
        WHEN 'ENGINEERING_BUILD' THEN 6
        WHEN 'ENGINEERING_CODE' THEN 7
        WHEN 'OPERATIONS_CORE' THEN 8
        WHEN 'OPERATIONS_AUTO' THEN 9
        WHEN 'CREATIVE_MEDIA' THEN 10
        WHEN 'CREATIVE_CONTENT' THEN 11
        WHEN 'SECURITY' THEN 12
        WHEN 'MEDICAL' THEN 13
        WHEN 'AWAY_TEAM' THEN 14
        WHEN 'INFRASTRUCTURE' THEN 15
        WHEN 'FINANCE' THEN 16
        WHEN 'DOCUMENTATION' THEN 17
        WHEN 'QA' THEN 18
        WHEN 'ADMIN' THEN 19
        WHEN 'SUPPORT' THEN 20
        ELSE position_order
    END
WHERE is_active = true;

-- ============================================
-- STEP 5: Verify workload balance
-- ============================================
CREATE OR REPLACE VIEW v_workload_balance AS
SELECT
    bs.station_code,
    bs.station_name,
    array_length(bs.modules, 1) as module_count,
    COUNT(DISTINCT sa.agent_id) as agent_count,
    bs.modules,
    CASE
        WHEN array_length(bs.modules, 1) <= 4 THEN 'OK'
        ELSE 'OVER_LIMIT'
    END as workload_status
FROM bridge_stations bs
LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = true
WHERE bs.is_active = true
GROUP BY bs.id, bs.station_code, bs.station_name, bs.modules
ORDER BY array_length(bs.modules, 1) DESC;

-- Grant permissions
GRANT SELECT ON v_workload_balance TO archie;

-- Add comment
COMMENT ON VIEW v_workload_balance IS 'Shows workload distribution per station with 4-module limit enforcement';
