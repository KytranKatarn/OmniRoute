-- Migration 046: Module Required Skills Mapping
-- Purpose: Map each module to its required skills for skills-based assignment validation
-- Date: 2026-01-20
-- User Requirement: Block assignment if agent lacks matching skills

-- Create the module_required_skills table
CREATE TABLE IF NOT EXISTS module_required_skills (
    module_id VARCHAR(50) PRIMARY KEY,
    module_name VARCHAR(100) NOT NULL,
    required_skills TEXT[] NOT NULL,
    skill_category VARCHAR(50) NOT NULL,
    min_proficiency INTEGER DEFAULT 3 CHECK (min_proficiency >= 1 AND min_proficiency <= 5),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create index for skill lookups
CREATE INDEX IF NOT EXISTS idx_module_skills_category ON module_required_skills(skill_category);

-- Populate module skills mappings (60 modules organized by category)

-- ============================================
-- CREATION TOOLS (Orange theme)
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('project_builder', 'Project Builder', ARRAY['python', 'javascript', 'api_design', 'architecture'], 'development', 4),
('game_studio', 'Game Studio', ARRAY['javascript', 'python', 'creative_solutions'], 'development', 3),
('media_studio', 'Media Studio', ARRAY['creative_solutions', 'content_creation', 'media_processing'], 'creative', 3),
('content_studio', 'Content Studio', ARRAY['technical_writing', 'content_creation', 'summarization'], 'documentation', 3),
('app_builder', 'App Builder', ARRAY['python', 'javascript', 'api_design', 'architecture'], 'development', 4),
('website_builder', 'Website Builder', ARRAY['javascript', 'python', 'api_design'], 'development', 3),
('website_designer', 'Website Designer', ARRAY['javascript', 'python', 'api_design', 'creative_solutions'], 'development', 3),
('book_builder', 'Book Builder', ARRAY['technical_writing', 'summarization', 'content_creation'], 'documentation', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- DEVELOPMENT TOOLS (Red theme - Admin)
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('code_editor', 'Code Editor', ARRAY['python', 'javascript', 'code_review', 'best_practices'], 'development', 4),
('coderabbit', 'CodeRabbit', ARRAY['code_review', 'security_analysis', 'best_practices'], 'code_quality', 4),
('improvements_lab', 'Improvements Lab', ARRAY['architecture', 'code_review', 'python', 'javascript'], 'development', 4),
('sandbox_manager', 'Sandbox Manager', ARRAY['python', 'security_analysis', 'devops'], 'operations', 4),
('blueprint', 'Blueprint', ARRAY['architecture', 'project_management', 'strategic_planning'], 'architecture', 4),
('testing_suite', 'Testing Suite', ARRAY['python', 'javascript', 'bug_fixing', 'code_review'], 'code_quality', 3),
('cursor_integration', 'Cursor Integration', ARRAY['python', 'javascript', 'api_design'], 'development', 3),
('fine_tuning', 'Fine Tuning', ARRAY['python', 'machine_learning', 'complex_reasoning'], 'specialized', 4),
('api_docs', 'API Documentation', ARRAY['technical_writing', 'api_design', 'documentation'], 'documentation', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- BUSINESS TOOLS (Blue theme)
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('crm', 'CRM', ARRAY['customer_service', 'communication', 'data_management'], 'business', 3),
('invoicing', 'Invoicing', ARRAY['financial_analysis', 'data_management', 'communication'], 'business', 3),
('scheduler', 'Scheduler', ARRAY['operations_management', 'communication', 'data_management'], 'operations', 3),
('email_manager', 'Email Manager', ARRAY['communication', 'email_coordination', 'customer_service'], 'communication', 3),
('automations', 'Automations', ARRAY['python', 'api_design', 'workflow_automation'], 'operations', 3),
('google_workspace', 'Google Workspace', ARRAY['communication', 'data_management', 'calendar_management'], 'operations', 2),
('task_planner', 'Task Planner', ARRAY['project_management', 'operations_management', 'communication'], 'operations', 3),
('site_manager', 'Site Manager', ARRAY['javascript', 'python', 'web_development'], 'development', 3),
('call_center', 'Call Center', ARRAY['customer_service', 'communication', 'call_handling'], 'communication', 3),
('store_builder', 'Store Builder', ARRAY['javascript', 'e_commerce', 'customer_service'], 'business', 3),
('social_media', 'Social Media', ARRAY['content_creation', 'social_media_strategy', 'communication'], 'creative', 3),
('github_manager', 'GitHub Manager', ARRAY['python', 'git', 'code_review', 'devops'], 'development', 4),
('analytics_dashboard', 'Analytics Dashboard', ARRAY['data_analysis', 'financial_analysis', 'reporting'], 'analysis', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- STANDALONE APPS (Purple theme)
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('archie_chat', 'A.R.C.H.I.E. Chat', ARRAY['complex_reasoning', 'communication', 'python'], 'general', 4),
('archie_pool', 'Archie Pool', ARRAY['python', 'api_design', 'communication'], 'development', 3),
('pool_management', 'Pool Management', ARRAY['python', 'api_design', 'operations_management'], 'operations', 3),
('doc', 'DOC Medical', ARRAY['medical_knowledge', 'communication', 'empathy'], 'specialized', 4),
('therapy', 'Therapy', ARRAY['empathy', 'mental_health', 'communication'], 'specialized', 4),
('fitness', 'Fitness', ARRAY['health_knowledge', 'communication', 'motivation'], 'specialized', 3),
('stockbot', 'StockBot', ARRAY['financial_analysis', 'market_analysis', 'data_analysis'], 'business', 4),
('picture_generation', 'Picture Generation', ARRAY['creative_solutions', 'media_processing', 'content_creation'], 'creative', 3),
('video_generation', 'Video Generation', ARRAY['creative_solutions', 'media_processing', 'content_creation'], 'creative', 3),
('story_generation', 'Story Generation', ARRAY['creative_solutions', 'technical_writing', 'content_creation'], 'creative', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- ADMIN OPS (Red theme)
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('team_management', 'Team Management', ARRAY['leadership', 'communication', 'hr_management'], 'business', 4),
('hr_management', 'HR Management', ARRAY['hr_management', 'communication', 'policy_management'], 'business', 4),
('consciousness', 'Consciousness', ARRAY['complex_reasoning', 'memory_management', 'python'], 'architecture', 4),
('obsidian_vault', 'Obsidian Vault', ARRAY['knowledge_management', 'documentation', 'research'], 'documentation', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- ADMIN TOOLS (Red theme)
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('admin_tools', 'Admin Tools', ARRAY['administration', 'communication', 'data_management'], 'operations', 2),
('general_tasks', 'General Tasks', ARRAY['communication', 'administration', 'problem_solving'], 'general', 2),
('backup_manager', 'Backup Manager', ARRAY['devops', 'security_analysis', 'disaster_recovery'], 'operations', 4),
('security_network', 'Security Network', ARRAY['security_analysis', 'network_monitoring', 'threat_detection'], 'security', 4),
('account_center', 'Account Center', ARRAY['security_analysis', 'administration', 'communication'], 'security', 3),
('automation_services', 'Automation Services', ARRAY['python', 'api_design', 'workflow_automation'], 'operations', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- INFRASTRUCTURE
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('network_monitor', 'Network Monitor', ARRAY['network_monitoring', 'devops', 'security_analysis'], 'operations', 4),
('server_dashboard', 'Server Dashboard', ARRAY['devops', 'monitoring', 'infrastructure'], 'operations', 4),
('home_automation', 'Home Automation', ARRAY['iot', 'automation', 'python'], 'operations', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- DOCUMENTATION
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('docs_manager', 'Docs Manager', ARRAY['technical_writing', 'documentation', 'summarization'], 'documentation', 3),
('technical_writing', 'Technical Writing', ARRAY['technical_writing', 'documentation', 'communication'], 'documentation', 4)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- QA
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('qa_dashboard', 'QA Dashboard', ARRAY['code_review', 'bug_fixing', 'quality_assurance'], 'code_quality', 4),
('test_runner', 'Test Runner', ARRAY['python', 'javascript', 'testing', 'bug_fixing'], 'code_quality', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- AWAY TEAM / RESEARCH
-- ============================================
INSERT INTO module_required_skills (module_id, module_name, required_skills, skill_category, min_proficiency) VALUES
('web_scraper', 'Web Scraper', ARRAY['python', 'data_collection', 'research'], 'analysis', 3),
('research_agent', 'Research Agent', ARRAY['research', 'data_analysis', 'summarization'], 'analysis', 3),
('data_collector', 'Data Collector', ARRAY['data_collection', 'python', 'data_analysis'], 'analysis', 3)
ON CONFLICT (module_id) DO UPDATE SET
    required_skills = EXCLUDED.required_skills,
    updated_at = NOW();

-- ============================================
-- Create validation view for skill mismatches
-- ============================================
CREATE OR REPLACE VIEW v_agent_skill_mismatches AS
SELECT
    a.id as agent_id,
    a.name as agent_name,
    a.department,
    bs.station_code,
    m.module as module_id,
    mrs.module_name,
    mrs.required_skills,
    mrs.min_proficiency,
    COALESCE(
        ARRAY_AGG(DISTINCT ags.skill_name) FILTER (WHERE ags.skill_name = ANY(mrs.required_skills)),
        ARRAY[]::TEXT[]
    ) as matching_skills,
    COALESCE(
        MAX(ags.proficiency_level) FILTER (WHERE ags.skill_name = ANY(mrs.required_skills)),
        0
    ) as max_proficiency,
    CASE
        WHEN COALESCE(
            ARRAY_LENGTH(ARRAY_AGG(DISTINCT ags.skill_name) FILTER (WHERE ags.skill_name = ANY(mrs.required_skills)), 1),
            0
        ) = 0 THEN 'NO_MATCHING_SKILLS'
        WHEN COALESCE(
            MAX(ags.proficiency_level) FILTER (WHERE ags.skill_name = ANY(mrs.required_skills)),
            0
        ) < mrs.min_proficiency THEN 'PROFICIENCY_TOO_LOW'
        ELSE 'OK'
    END as validation_status
FROM agents a
JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = true
JOIN bridge_stations bs ON sa.station_id = bs.id
CROSS JOIN LATERAL unnest(bs.modules) as m(module)
LEFT JOIN module_required_skills mrs ON m.module = mrs.module_id
LEFT JOIN agent_skills ags ON a.id = ags.agent_id
WHERE a.status = 'active' AND a.worker_type = 'internal'
GROUP BY a.id, a.name, a.department, bs.station_code, m.module, mrs.module_name, mrs.required_skills, mrs.min_proficiency;

-- Create summary view for mismatched assignments
CREATE OR REPLACE VIEW v_skill_mismatch_summary AS
SELECT
    validation_status,
    COUNT(*) as assignment_count,
    COUNT(DISTINCT agent_id) as unique_agents,
    COUNT(DISTINCT module_id) as unique_modules
FROM v_agent_skill_mismatches
WHERE validation_status != 'OK'
GROUP BY validation_status;

-- Grant permissions
GRANT SELECT ON module_required_skills TO archie;
GRANT SELECT ON v_agent_skill_mismatches TO archie;
GRANT SELECT ON v_skill_mismatch_summary TO archie;

-- Add comment
COMMENT ON TABLE module_required_skills IS 'Maps modules to their required skills for skills-based agent assignment validation';
