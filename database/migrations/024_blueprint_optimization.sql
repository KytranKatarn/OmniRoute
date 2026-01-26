-- ============================================
-- Phase 29: Blueprint Module Optimization
-- Date: 2026-01-17
-- Description: Database-driven roadmap, platform inventory, cleanup management
-- ============================================

-- 1. Blueprint Phases (migrate from hardcoded routes.py)
CREATE TABLE IF NOT EXISTS blueprint_phases (
    id SERIAL PRIMARY KEY,
    phase_number VARCHAR(20) NOT NULL UNIQUE,  -- e.g., '1', '4.5', 'W1' for workflow
    name VARCHAR(255) NOT NULL,
    section VARCHAR(100) NOT NULL,  -- 'foundation', 'workflow', 'modules', 'future'
    status VARCHAR(30) DEFAULT 'planned',  -- planned, in_progress, completed, blocked
    description TEXT,
    completion_percent INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    display_order INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Blueprint Phase Tasks
CREATE TABLE IF NOT EXISTS blueprint_tasks (
    id SERIAL PRIMARY KEY,
    phase_id INTEGER REFERENCES blueprint_phases(id) ON DELETE CASCADE,
    task_description TEXT NOT NULL,
    done BOOLEAN DEFAULT FALSE,
    display_order INTEGER NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- 3. Platform Inventory Snapshots
CREATE TABLE IF NOT EXISTS platform_inventory (
    id SERIAL PRIMARY KEY,
    snapshot_at TIMESTAMP DEFAULT NOW(),
    snapshot_type VARCHAR(50) DEFAULT 'full',  -- full, docs, tools, migrations
    total_python_files INTEGER,
    total_docs INTEGER,
    total_tools INTEGER,
    total_migrations INTEGER,
    total_size_mb DECIMAL(10,2),
    inventory_data JSONB NOT NULL,  -- Full file listing with sizes
    is_current BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_by VARCHAR(100) DEFAULT 'system'
);

-- 4. Cleanup Candidates
CREATE TABLE IF NOT EXISTS platform_cleanup_candidates (
    id SERIAL PRIMARY KEY,
    file_path TEXT NOT NULL,
    file_type VARCHAR(50),  -- 'python', 'html', 'markdown', 'directory'
    category VARCHAR(50),  -- 'deprecated', 'orphaned', 'duplicate', 'outdated'
    file_size_bytes BIGINT,
    reason TEXT,
    action_recommended VARCHAR(30) DEFAULT 'review',  -- archive, delete, merge, keep
    status VARCHAR(30) DEFAULT 'pending',  -- pending, approved, executed, rejected
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bp_phases_status ON blueprint_phases(status);
CREATE INDEX IF NOT EXISTS idx_bp_phases_section ON blueprint_phases(section);
CREATE INDEX IF NOT EXISTS idx_bp_tasks_phase ON blueprint_tasks(phase_id);
CREATE INDEX IF NOT EXISTS idx_bp_inventory_current ON platform_inventory(is_current) WHERE is_current = true;
CREATE INDEX IF NOT EXISTS idx_bp_cleanup_status ON platform_cleanup_candidates(status);
CREATE INDEX IF NOT EXISTS idx_bp_cleanup_category ON platform_cleanup_candidates(category);

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_blueprint_phases_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS blueprint_phases_updated ON blueprint_phases;
CREATE TRIGGER blueprint_phases_updated
    BEFORE UPDATE ON blueprint_phases
    FOR EACH ROW
    EXECUTE FUNCTION update_blueprint_phases_timestamp();

-- ============================================
-- SEED DATA: All 42+ Phases from routes.py
-- ============================================

-- Section: PLATFORM FOUNDATION
INSERT INTO blueprint_phases (phase_number, name, section, status, display_order) VALUES
('1', 'Database Schema Unification', 'foundation', 'completed', 1),
('2', 'Unified Brain Interface', 'foundation', 'completed', 2),
('3', 'AI Bridge Local-First', 'foundation', 'completed', 3),
('4', 'Mistake Learning & Prevention', 'foundation', 'completed', 4),
('4.5', 'Claude Code Integration', 'foundation', 'completed', 5);

-- Section: IMPROVEMENT WORKFLOW (v4.0)
INSERT INTO blueprint_phases (phase_number, name, section, status, display_order) VALUES
('W1', 'Workflow Phase 1: Foundation', 'workflow', 'completed', 6),
('W2', 'Workflow Phase 2: Enhanced Chat', 'workflow', 'completed', 7),
('W3', 'Workflow Phase 3: Team Assignment', 'workflow', 'completed', 8),
('W4', 'Workflow Phase 4: Sandbox System', 'workflow', 'completed', 9),
('W5', 'Workflow Phase 5: Deployment Pipeline', 'workflow', 'completed', 10),
('W6', 'Workflow Phase 6: Full Integration', 'workflow', 'completed', 11),
('W7', 'Workflow Phase 7: UI Polish', 'workflow', 'completed', 12),
('W8', 'Workflow Phase 8: Test Retry Loop + Contractor Escalation', 'workflow', 'completed', 13),
('W9', 'Workflow Phase 9: Improvements Lab UI Rebuild', 'workflow', 'completed', 14),
('W10', 'Workflow Phase 10: Team Management UI Updates', 'workflow', 'completed', 15),
('W11', 'Workflow Phase 11: Backup Manager v2', 'workflow', 'completed', 16),
('W12', 'Workflow Phase 12: Improvements Lab Workflow Fixes', 'workflow', 'completed', 17),
('W13', 'Workflow Phase 13: External Watchdog Auto-Rollback', 'workflow', 'completed', 18),
('W14', 'Workflow Phase 14: CodeRabbit Integration Fix', 'workflow', 'completed', 19),
('W15', 'Workflow Phase 15: Team Management Personality System', 'workflow', 'completed', 20),
('16', 'V2 Code Generation Engine', 'workflow', 'completed', 21),
('17', 'Team Skills & HR Dashboard', 'workflow', 'completed', 22),
('18', 'CodeRabbit v2.0.0 Optimization', 'workflow', 'completed', 23),
('19', 'PR Workflow & Git Hooks', 'workflow', 'completed', 24),
('20', 'CodeRabbit → Improvements Lab Integration', 'workflow', 'completed', 25),
('21', 'Git Manager Consolidation', 'workflow', 'completed', 26),
('22', 'Dashboard Layout Restructuring', 'workflow', 'completed', 27),
('23', 'Sandbox System Completion', 'workflow', 'completed', 28),
('24', 'Backup Manager Integration', 'workflow', 'completed', 29),
('25', 'Website Designer Chat-Based Editor', 'workflow', 'in_progress', 30);

-- Section: MODULE DEVELOPMENT
INSERT INTO blueprint_phases (phase_number, name, section, status, display_order) VALUES
('5', 'Module Consolidation', 'modules', 'in_progress', 31),
('6', 'Business Tools Integration', 'modules', 'completed', 32),
('7', 'Standalone Apps', 'modules', 'planned', 33);

-- Section: FUTURE FEATURES
INSERT INTO blueprint_phases (phase_number, name, section, status, display_order) VALUES
('26', 'A.R.C.H.I.E. Bridge - Core UI', 'future', 'completed', 34),
('27', 'A.R.C.H.I.E. Bridge - LLM Monitor', 'future', 'completed', 35),
('28', 'Consciousness Optimization & Shift Scheduler', 'future', 'completed', 36),
('29', 'Blueprint Module Optimization', 'future', 'in_progress', 37),
('30', 'Mining Pool Integration', 'future', 'planned', 38),
('31', 'Bridge Station Restructure', 'future', 'in_progress', 39),
('32', 'Per-Agent Memory Tables', 'future', 'completed', 40),
('33', 'Agent Emotional State Tracking', 'future', 'completed', 41),
('34', 'IAAE Ethics Constraints', 'future', 'completed', 42),
('35', 'Governance Audit System', 'future', 'completed', 43),
('36', 'Rest Cycle Implementation', 'future', 'completed', 44),
('37', 'Task Refusal System', 'future', 'completed', 45),
('38', 'Ethics Agent Deployment', 'future', 'planned', 46),
('39', 'Station Assignment UI', 'future', 'planned', 47),
('40', 'IAAE Compliance Dashboard', 'future', 'planned', 48),
('41', 'Admin Operations Hub', 'future', 'completed', 49),
('42', 'Conversation Triage System', 'future', 'completed', 50),
('8', 'Figma Integration', 'future', 'planned', 51),
('9', 'Long-Term Memory', 'future', 'planned', 52),
('10', 'Production Launch', 'future', 'planned', 53);

-- ============================================
-- SEED DATA: Tasks for Each Phase
-- ============================================

-- Phase 1: Database Schema Unification
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '1'), 'Single knowledge_base table (2,490+ entries)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '1'), 'Migrate from fragmented systems', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '1'), 'Helper functions and views', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '1'), 'Type-based organization (6 types)', true, 4);

-- Phase 2: Unified Brain Interface
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '2'), 'Admin dashboard at /tools/admin/brain', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '2'), 'unified_knowledge_search.py', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '2'), '6 API routes for knowledge management', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '2'), 'Type-weighted ranking system', true, 4);

-- Phase 3: AI Bridge Local-First
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '3'), 'knowledge_retrieval.py integration', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '3'), '3-step retrieval: mistakes → knowledge → memory', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '3'), 'Local knowledge checked BEFORE external APIs', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '3'), '4-6x faster queries, cost savings', true, 4);

-- Phase 4: Mistake Learning & Prevention
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '4'), 'mistake_detector.py with 14 error patterns', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '4'), 'Flask error handler integration', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '4'), 'Automatic learning from exceptions', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '4'), '4 API routes for mistake management', true, 4);

-- Phase 4.5: Claude Code Integration
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '4.5'), 'PreCompact & SessionEnd hooks', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '4.5'), 'Conversation monitoring & saving', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '4.5'), 'Git worktrees structure', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '4.5'), 'CLAUDE.md project memory', true, 4);

-- Workflow Phase 1: Foundation
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W1'), 'Database migration (5 tables, 8 columns, 12 indexes)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W1'), 'Stuck proposal detection & auto-escalation', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W1'), 'Team assignment engine skeleton', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W1'), 'Notification system integration', true, 4);

-- Workflow Phase 2: Enhanced Chat
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W2'), 'Natural language proposal creation', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W2'), 'Code diff engine with syntax highlighting', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W2'), 'Step-by-step guidance generator', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W2'), '4 new API endpoints', true, 4);

-- Workflow Phase 3: Team Assignment
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W3'), 'team_assignment_engine.py (18K)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W3'), 'Internal-first routing (90% internal usage)', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W3'), 'Skill-based matching', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W3'), '6 team management API endpoints', true, 4);

-- Workflow Phase 4: Sandbox System
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W4'), 'sandbox_manager.py orchestrator (26K)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W4'), 'Schema-based sandboxes (122 tables, <1s)', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W4'), 'Docker-based sandboxes for high-risk', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W4'), 'Test runner (syntax, security, health)', true, 4);

-- Workflow Phase 5: Deployment Pipeline
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W5'), 'safe_deployment_protocol.py (20K)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W5'), 'deployment_decision.py risk assessment', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W5'), 'Pre-deployment backup automation', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W5'), 'deployment_monitor.py (24hr monitoring)', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W5'), 'Deploy-to-production with issue tracking', true, 5);

-- Workflow Phase 6: Full Integration
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'CodeRabbit → Improvements Lab flow', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'Send to Improvements button with duplicate prevention', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'Per-module sandbox architecture (6 sandboxes)', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'Sandbox Manager UI with visual access', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'Full workflow: scan → proposal → test → deploy → fixed', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'Issue status tracking (fixed_at, fixed_by)', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W6'), 'code_fixes audit trail', true, 7);

-- Workflow Phase 7: UI Polish
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W7'), 'Status filter dropdown (12 statuses)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W7'), 'Delete proposal button with cascade', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W7'), 'Confirmation dialogs with proposal titles', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W7'), 'Database cleanup tools', true, 4);

-- Workflow Phase 8: Test Retry Loop
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), 'Database migration 025 (retry tracking, escalation, chat)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), 'test_retry_handler.py (automatic retry up to 3x)', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), 'Contractor routing in archie_bridge.py', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), 'chat_handler.py for fluid human-contractor chat', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), 'Strict queue enforcement (one proposal at a time)', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), '10 new API endpoints for retry/escalation/chat', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W8'), 'Agent personality system (personality_prompt, communication_style)', true, 7);

-- Workflow Phase 9: Improvements Lab UI Rebuild
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Refactor from 4,340 lines to modular architecture', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Create api.js - centralized API calls (304 lines)', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Create ui.js - notifications, modals, utilities (431 lines)', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Create app.js - state management, 25 async functions (965 lines)', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Slim HTML template (291 lines)', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Proposal list with filters and cards', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Sandbox viewer with test controls', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Contractor chat panel with escalation', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'Queue status display', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W9'), 'All button interactions wired up', true, 10);

-- Workflow Phase 10: Team Management UI Updates
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W10'), 'Add personality prompt editor for agents', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W10'), 'Add communication style selector', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W10'), 'Show agent work history on proposals', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W10'), 'Display contractor API status and availability', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W10'), 'Integration with escalation workflow', true, 5);

-- Workflow Phase 11: Backup Manager v2
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Consolidate duplicate backup_manager files', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Fix path constants for modular architecture', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Add programmatic create_backup() function', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Add backup_module() for module-level backups', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Add get_module_dependencies() helper', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Fix imports in improvements/routes.py', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Fix imports in safe_deployment_protocol.py', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Delete old backup_manager.py', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Create /docs/BACKUP_MANAGER_GUIDE.md', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Add API endpoints for module backups', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Fix build number tracking', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Implement backup types (full/critical/database/custom)', true, 12),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Add Module Backups UI section', true, 13),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Add all 11 components backup', true, 14),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Fix docker volume mounts for full backup access', true, 15),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W11'), 'Verify disaster recovery (58MB, 264 tables)', true, 16);

-- Workflow Phase 12: Improvements Lab Workflow Fixes
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix execute endpoint (400 error on empty body)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Add Regenerate Plan button for legacy proposals', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix AI code parser for markdown format', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix Security Scan test (check recent files only)', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix test status logic (required vs non-required)', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix Logs endpoint to show test results', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix deploy test_status check', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Implement actual code deployment', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Fix container path mapping', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W12'), 'Test full deploy to production', true, 10);

-- Workflow Phase 13: External Watchdog
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Create POSIX shell watchdog script', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Watchdog runs in docker:cli container', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Crash loop detection (restarting status)', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Sustained healthy check (20s requirement)', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Auto-restore from backup using modified_files', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Database rollback status updates', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Restart endpoint launches external watchdog', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W13'), 'Test with intentional crash - SUCCESS', true, 8);

-- Workflow Phase 14: CodeRabbit Integration Fix
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W14'), 'Fix AI-generated fixes to match actual code', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W14'), 'Read actual file content before generating fix', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W14'), 'Validate paths (Docker + host) before generating', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W14'), 'Strip line numbers from AI output', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W14'), 'Feedback loop: deploy success → mark issue fixed', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W14'), 'End-to-end test: CodeRabbit → Deploy verified', true, 6);

-- Workflow Phase 15: Team Management Personality
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Add personality prompt editor textarea', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Add communication style selector dropdown', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Show agent work history', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Display contractor API status', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Add /api/agents/<id>/work-history endpoint', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Add /api/agents/<id>/contractor-status endpoint', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = 'W15'), 'Integration with escalation workflow ready', true, 7);

-- Phase 16: V2 Code Generation Engine
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Implement Architect/Editor pattern for 85% accuracy', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Add syntax validation (ast.parse + py_compile)', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Add content matching verification', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Add smart snippet validation', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Add retry logic with error feedback (max 3)', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Add Team Management integration', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Fix code_application_system to fail on mismatch', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '16'), 'Create CODE_GENERATION_ENGINE_V2.md documentation', true, 8);

-- Phase 17: Team Skills & HR Dashboard
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Create migration to populate agent_skills table (959 records)', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Map models to skill strengths (18 model mappings)', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Add Skills API endpoints (8 new routes)', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Add Skills tab to Team Management UI', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Add HR Dashboard tab with model performance comparison', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Skills matrix view (agents x skills)', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Skill gaps identification', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Skill-based recommendations engine', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Integrate skills with V2 code generation', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '17'), 'Update A.R.C.H.I.E. Blueprints', true, 10);

-- Phase 18: CodeRabbit v2.0.0
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add proposal_id column to code_issues table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Fix git commit parameter mismatch', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add modified file detection', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add Rescan Modified batch button', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add bidirectional issue tracking', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add status-aware proposal badges', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add CodeRabbit review status on PRs', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add Request Review button', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Add sessionStorage scan cache', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Fix folder toggle quote escaping', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '18'), 'Update CODERABBIT_MODULE.md to v2.0.0', true, 11);

-- Phase 19: PR Workflow & Git Hooks
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '19'), 'Create .coderabbit.yaml for auto-reviews', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '19'), 'Create pre-push git hook for protected branches', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '19'), 'Create install-git-hooks.sh script', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '19'), 'Create PR_WORKFLOW_CODERABBIT.md documentation', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '19'), 'Test CodeRabbit auto-review on PR #3', true, 5);

-- Phase 20: CodeRabbit → Improvements Lab Integration
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add /api/pr/<number>/review-comments endpoint', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add /api/pr/suggestions-to-improvements endpoint', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add /api/pr/<number>/merge endpoint', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add /api/git/create-pr endpoint', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add Create PR section in Local Git tab', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add Suggestions button on reviewed PRs', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add suggestions modal with checkboxes', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Add Merge PR button on open PRs', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Auto-categorize suggestions', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Track PR context in proposals', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '20'), 'Test full workflow: PR → Review → Proposal', true, 11);

-- Phase 21: Git Manager Consolidation
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Disable GitHub Manager module', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Rename Local Git tab to Git Manager', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add /api/git/branches endpoint', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add /api/git/create-branch endpoint', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add /api/git/checkout endpoint', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add /api/git/delete-branch endpoint', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add branch selector dropdown UI', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add branch list with delete buttons', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add Create Branch modal', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add GitHub Issues tab', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add GitHub Actions tab', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add protected branch enforcement', true, 12),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Update CODERABBIT_MODULE.md to v2.2.0', true, 13),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Update MODULE_REGISTRY_STATUS.md', true, 14),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Add CI workflow', true, 15),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'CI: Lint & Syntax Check job', true, 16),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'CI: Security Scan job', true, 17),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'CI: Docker Build Test job', true, 18),
((SELECT id FROM blueprint_phases WHERE phase_number = '21'), 'Test GitHub Actions tab with live workflow runs', true, 19);

-- Phase 22: Dashboard Layout Restructuring
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Move A.R.C.H.I.E. Chat to STANDALONE_APPS', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Disable Code Editor', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Disable Business Directory', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Move Improvements Lab to DEVELOPMENT', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Move Sandbox Manager to DEVELOPMENT', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Rename Website Studio → Website Designer', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'DEVELOPMENT category RED styling', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'ADMIN category RED styling', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'ADMIN ONLY badge on DEVELOPMENT section', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Add Code View tab (Monaco-style editor)', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Add Preview tab (live HTML preview)', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Add Business Directory tab', true, 12),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Add Git tab', true, 13),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Add Domains tab', true, 14),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Create hostinger_integration.py', true, 15),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Add DNS presets', true, 16),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Per-user Business Directory', true, 17),
((SELECT id FROM blueprint_phases WHERE phase_number = '22'), 'Update MASTER_STATUS_AND_ROADMAP_2026.md', true, 18);

-- Phase 23: Sandbox System Completion
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Verify Migration 007', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Verify Migration 020', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Create Migration 021', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Sandbox Manager template verified', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Auto-backup on deploy-to-production', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Deployment tracking in improvement_deployments', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Post-deployment health checks', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Auto-sandbox creation on proposal approval', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Module detection from file paths', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'v_recent_improvement_deployments view', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'v_improvement_deployment_stats view', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'AI Bridge environment awareness', true, 12),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Auto-restart container after Python deployments', true, 13),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Deployment status tracking', true, 14),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'PR review feedback loop', true, 15),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'CodeRabbit → Deploy → Fixed workflow', true, 16),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Sandbox Manager UI modernization', true, 17),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Tab navigation', true, 18),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Schema/Docker type badges', true, 19),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'API endpoints', true, 20),
((SELECT id FROM blueprint_phases WHERE phase_number = '23'), 'Update Blueprint with Phase 23', true, 21);

-- Phase 24: Backup Manager Integration
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '24'), 'UI Modernization', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '24'), 'Tab navigation', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '24'), 'Deployment Backups tab', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '24'), 'Cross-module navigation links', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '24'), 'API endpoint: /api/deployment-backups', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '24'), 'Stats grid with deployment count', true, 6);

-- Phase 25: Website Designer Chat-Based Editor
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Create chat_handler.py for chat-to-code pipeline', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'POST /api/chat endpoint', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'POST /api/apply-changes endpoint', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'POST /api/deploy-to-github-pages endpoint', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'GET /api/preview endpoint', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'GET/POST /api/chat/history endpoint', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Three-panel UI (Chat | Preview | Code)', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Dark cyberpunk theme', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Tab navigation: Chat Designer, Projects, Git', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Create UI_STYLE_GUIDE.md documentation', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Create WEBSITE_DESIGNER_MODULE.md documentation', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Fix Preview panel display issues', false, 12),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Improve file/folder selection UI', false, 13),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Git tab detail improvements', false, 14),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Monaco Editor integration', false, 15),
((SELECT id FROM blueprint_phases WHERE phase_number = '25'), 'Client mockup project templates', false, 16);

-- Phase 5: Module Consolidation
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Consolidate duplicate modules', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Add STANDALONE_APPS category', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Add BUSINESS_TOOLS category', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Module registry with 32 modules', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'A.R.C.H.I.E. Blueprint module', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'CodeRabbit module with GitHub integration', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'CodeRabbit dashboard with live PR stats', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'GitHub repo connected', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Code Health Scanner with AI + Static analysis', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'File scanning with Ollama integration', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Collapsible folder UI', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Batch scanning', true, 12),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Scan results persistence in database', true, 13),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Knowledge base integration', true, 14),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Auto-create improvement proposals', true, 15),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Fix audit trail', true, 16),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Documentation audit', true, 17),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Archive obsolete docs', true, 18),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Update admin panel references', true, 19),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Fix Claude Code hooks configuration', true, 20),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Implement Project Builder UI', false, 21),
((SELECT id FROM blueprint_phases WHERE phase_number = '5'), 'Implement Media Studio UI', false, 22);

-- Phase 6: Business Tools Integration
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'CRM Module', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Email Manager', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Invoicing Module', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Scheduler Module', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Analytics Module', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Automations Module', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Social Media Module', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Call Center', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'Store + Website integration', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '6'), 'STORE.KytranEmpowerment.com deployment', true, 10);

-- Phase 7: Standalone Apps
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '7'), 'DOC - Medical AI assistant', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '7'), 'Therapy - Mental health AI', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '7'), 'Fitness - AI fitness coach', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '7'), 'StockBot - AI stock screener', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '7'), 'Archie Pool user dashboard', false, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '7'), 'Pool Management admin interface', false, 6);

-- Phase 26: A.R.C.H.I.E. Bridge - Core UI
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Create /tools/bridge/ route and blueprint', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Design Bridge template with station layout', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Real-time stats', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Station cards with agent avatars', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Captain/First Officer status bar', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Click station -> navigate to modules', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '26'), 'Dark cyberpunk theme', true, 7);

-- Phase 27: A.R.C.H.I.E. Bridge - LLM Monitor
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Create llm_connections database table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Health check background service', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Provider-specific checks', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Connection status API endpoints', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'LLM Connections Monitor panel', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Alert system for connection failures', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Bridge icon updated', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Admin Ops modules display', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '27'), 'Naming standardized to Consciousness', true, 9);

-- Phase 28: Consciousness Optimization & Shift Scheduler
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Consciousness Dashboard UI overhaul with Chart.js', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Knowledge Graph D3.js visualization', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Emotional State dashboard', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Live Activity Feed', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Shift Scheduler with calendar', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Lean Staffing Matrix', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Shift-aware routing in archie_bridge', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '28'), 'Conflict detection system', true, 8);

-- Phase 29: Blueprint Module Optimization
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Create database migration 024', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Migrate 42+ phases to database', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Create phase_manager.py', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Create inventory_scanner.py', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Create cleanup_manager.py', false, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Add 15+ API endpoints', false, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Add INVENTORY tab', false, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Add CLEANUP tab', false, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Archive old phase docs', false, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '29'), 'Execute code cleanup', false, 10);

-- Phase 30-42 and 8-10: Future phases with basic tasks (abbreviated)
INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order) VALUES
((SELECT id FROM blueprint_phases WHERE phase_number = '30'), 'Review mining pool documentation', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '30'), 'Design dual-purpose scheduler', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '30'), 'Integrate with Bridge for resource management', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '31'), 'Expand Bridge from 5 to 10 stations', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '31'), 'Create bridge_stations table with seed data', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '31'), 'Update Bridge UI template for 3-row layout', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '31'), 'Add station configuration APIs', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '31'), 'Create BRIDGE_STATION_ARCHITECTURE.md', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '32'), 'Create agent_memory table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '32'), 'Implement soft-delete with IAAE compliance', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '32'), 'Add memory CRUD endpoints', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '32'), 'Update consciousness module', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '33'), 'Create agent_emotional_state table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '33'), 'Implement bounds checking', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '33'), 'Add automatic interventions', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '33'), 'Create emotional dashboard widget', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '34'), 'Create ethics_constraints table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '34'), 'Seed 13 default constraints', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '34'), 'Implement constraint checking middleware', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '34'), 'Add ethics constraint management UI', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '34'), 'Create IAAE_GOVERNANCE_FRAMEWORK.md', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '35'), 'Create governance_audit_log table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '35'), 'Implement logging for all IAAE events', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '35'), 'Create audit log viewer UI', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '35'), 'Add compliance reporting', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '36'), 'Create agent_rest_cycles table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '36'), 'Implement automatic rest triggers', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '36'), 'Add rest cycle management API', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '36'), 'Create monitoring dashboard', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '37'), 'Create task_refusal_log table', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '37'), 'Implement refusal conditions', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '37'), 'Add override workflow', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '37'), 'Create refusal analytics', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '38'), 'Create Ethics Watchdog agent', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '38'), 'Implement monitoring routines', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '38'), 'Set up weekly compliance reports', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '38'), 'Configure alert triggers', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '39'), 'Create drag-and-drop assignment interface', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '39'), 'Implement real-time station roster', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '39'), 'Add shift scheduling UI', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '39'), 'Create station activity dashboard', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '40'), 'Add IAAE tab to Blueprint module', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '40'), 'Create compliance status indicators', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '40'), 'Implement agent welfare metrics', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '40'), 'Add IAAE documentation links', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '40'), 'Agent Mini-Chat in Team Management', false, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '40'), 'Integrate notifications with IAAE alerts', false, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Add ADMIN_OPS category to ModuleCategory enum', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Add admin_ops category to dashboard_generator.py', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Move Bridge, Team Management, Consciousness to ADMIN_OPS', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Update Bridge branding', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Update Consciousness branding', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Add cross-navigation buttons', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Modernize Team Management UI', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Add Station Assignment tab', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '41'), 'Create IAAE_TECHNICAL_ALIGNMENT.md', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Create conversation_triage module', true, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Implement conversation classifier', true, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Implement error/mistake extractor', true, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Implement code snippet extractor', true, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Implement insight extractor', true, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Create triage database tables', true, 6),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Update pre-compact hook for triage queue', true, 7),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Create triage API routes', true, 8),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Register triage blueprint in app.py', true, 9),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Create Knowledge Management agents (4)', true, 10),
((SELECT id FROM blueprint_phases WHERE phase_number = '42'), 'Assign agents to Consciousness station', true, 11),
((SELECT id FROM blueprint_phases WHERE phase_number = '8'), 'OAuth 2.0 authentication', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '8'), 'Design parser & analyzer', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '8'), 'AI component mapper', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '8'), 'React code generation', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '8'), 'Preview system & export', false, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '9'), 'Enhanced memory schema', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '9'), 'Memory collection points', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '9'), 'Semantic search (embeddings)', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '9'), 'Agent memory integration', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '9'), 'Memory dashboard UI', false, 5),
((SELECT id FROM blueprint_phases WHERE phase_number = '10'), 'Domain setup (archie-platform.com)', false, 1),
((SELECT id FROM blueprint_phases WHERE phase_number = '10'), 'SSL/Security audit', false, 2),
((SELECT id FROM blueprint_phases WHERE phase_number = '10'), 'Billing integration', false, 3),
((SELECT id FROM blueprint_phases WHERE phase_number = '10'), 'API documentation (OpenAPI)', false, 4),
((SELECT id FROM blueprint_phases WHERE phase_number = '10'), 'Mobile apps (Android/iOS)', false, 5);

-- Update completion percentages based on tasks
UPDATE blueprint_phases p SET completion_percent = (
    SELECT COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE done = true) / NULLIF(COUNT(*), 0)), 0)
    FROM blueprint_tasks t WHERE t.phase_id = p.id
);

-- Mark completion timestamps for completed phases
UPDATE blueprint_phases SET completed_at = NOW() WHERE status = 'completed';
UPDATE blueprint_phases SET started_at = NOW() - INTERVAL '30 days' WHERE status IN ('completed', 'in_progress');

-- ============================================
-- VERIFY: Count tables and records
-- ============================================
DO $$
DECLARE
    phase_count INTEGER;
    task_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO phase_count FROM blueprint_phases;
    SELECT COUNT(*) INTO task_count FROM blueprint_tasks;
    RAISE NOTICE 'Phase 29 Migration Complete: % phases, % tasks created', phase_count, task_count;
END $$;
