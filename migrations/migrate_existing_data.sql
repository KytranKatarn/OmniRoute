-- Migrate Existing Data to Unified Project System
-- A.R.C.H.I.E. Platform v5.24.0
-- Phase 65: Data Migration
-- Created: 2026-01-25

BEGIN;

-- ============================================================================
-- STEP 1: Create Parent Project for Blueprint Roadmap
-- ============================================================================

INSERT INTO unified_projects (
    name, slug, description, status, priority, project_type, tags
) VALUES (
    'A.R.C.H.I.E. Development Roadmap',
    'archie-roadmap',
    'Main development roadmap for A.R.C.H.I.E. platform. Contains all phases migrated from Blueprint module.',
    'active',
    10,
    'infrastructure',
    ARRAY['roadmap', 'blueprint', 'migrated']
) ON CONFLICT (slug) DO NOTHING;

-- Get the roadmap project ID
DO $$
DECLARE
    roadmap_id INTEGER;
    phase_rec RECORD;
    task_rec RECORD;
    new_project_id INTEGER;
    new_task_id INTEGER;
BEGIN
    SELECT id INTO roadmap_id FROM unified_projects WHERE slug = 'archie-roadmap';

    -- ============================================================================
    -- STEP 2: Migrate Blueprint Phases to Sub-Projects
    -- ============================================================================

    FOR phase_rec IN
        SELECT id, phase_number, name, section, status, description,
               completion_percent, display_order, created_at
        FROM blueprint_phases
        ORDER BY display_order
    LOOP
        -- Create project for each phase
        INSERT INTO unified_projects (
            name,
            slug,
            description,
            status,
            priority,
            project_type,
            parent_project_id,
            tags,
            metadata,
            created_at
        ) VALUES (
            'Phase ' || phase_rec.phase_number || ': ' || phase_rec.name,
            'phase-' || LOWER(REGEXP_REPLACE(phase_rec.phase_number, '[^a-zA-Z0-9]', '-', 'g')),
            COALESCE(phase_rec.description, phase_rec.name),
            CASE
                WHEN phase_rec.status = 'completed' OR phase_rec.status = 'complete' THEN 'completed'
                WHEN phase_rec.status = 'active' OR phase_rec.status = 'in_progress' THEN 'active'
                ELSE 'planning'
            END,
            CASE
                WHEN phase_rec.status IN ('completed', 'complete') THEN 3
                WHEN phase_rec.status IN ('active', 'in_progress') THEN 8
                ELSE 5
            END,
            'infrastructure',
            roadmap_id,
            ARRAY['phase', phase_rec.section, 'migrated'],
            jsonb_build_object(
                'original_phase_id', phase_rec.id,
                'phase_number', phase_rec.phase_number,
                'section', phase_rec.section,
                'completion_percent', phase_rec.completion_percent
            ),
            COALESCE(phase_rec.created_at, NOW())
        )
        ON CONFLICT (slug) DO UPDATE SET
            metadata = unified_projects.metadata || jsonb_build_object('migrated_again', NOW())
        RETURNING id INTO new_project_id;

        -- Create ARCHIE awareness for this project
        INSERT INTO archie_project_awareness (
            project_id,
            understanding_level,
            notes,
            emotional_association
        ) VALUES (
            new_project_id,
            CASE WHEN phase_rec.status IN ('completed', 'complete') THEN 100 ELSE 50 END,
            'Migrated from Blueprint phase ' || phase_rec.phase_number,
            CASE
                WHEN phase_rec.status IN ('completed', 'complete') THEN 'confident'
                WHEN phase_rec.status IN ('active', 'in_progress') THEN 'focused'
                ELSE 'curious'
            END
        ) ON CONFLICT (project_id) DO NOTHING;

        -- Migrate tasks for this phase
        FOR task_rec IN
            SELECT id, task_description, done, notes, created_at, completed_at
            FROM blueprint_tasks
            WHERE phase_id = phase_rec.id
            ORDER BY display_order
        LOOP
            INSERT INTO unified_tasks (
                project_id,
                title,
                description,
                status,
                priority,
                task_type,
                metadata,
                created_at,
                completed_at
            ) VALUES (
                new_project_id,
                LEFT(task_rec.task_description, 500),
                task_rec.notes,
                CASE WHEN task_rec.done THEN 'completed' ELSE 'pending' END,
                5,
                'implementation',
                jsonb_build_object('original_task_id', task_rec.id),
                COALESCE(task_rec.created_at, NOW()),
                task_rec.completed_at
            );
        END LOOP;

    END LOOP;

    RAISE NOTICE 'Migrated % phases as sub-projects under roadmap ID %',
        (SELECT COUNT(*) FROM blueprint_phases), roadmap_id;
END $$;

-- ============================================================================
-- STEP 3: Create System Project for Configuration Tracking
-- ============================================================================

INSERT INTO unified_projects (
    name, slug, description, status, priority, project_type, tags
) VALUES (
    'A.R.C.H.I.E. System Configuration',
    'system-config',
    'Tracks all system configuration changes, module updates, and platform settings.',
    'active',
    9,
    'infrastructure',
    ARRAY['system', 'config', 'consciousness']
) ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- STEP 4: Create Documentation Project
-- ============================================================================

INSERT INTO unified_projects (
    name, slug, description, status, priority, project_type, tags
) VALUES (
    'A.R.C.H.I.E. Documentation',
    'documentation',
    'Platform documentation, guides, and reference materials.',
    'active',
    7,
    'documentation',
    ARRAY['docs', 'guides', 'reference']
) ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- STEP 5: Log the migration as a configuration change
-- ============================================================================

INSERT INTO archie_config_history (
    config_type,
    config_path,
    change_type,
    change_reason,
    impact_assessment,
    new_value
) VALUES (
    'database',
    'unified_projects, unified_tasks',
    'created',
    'Phase 65: Data migration from Blueprint module to Unified Project System',
    'Blueprint phases and tasks now tracked in unified system. Original data preserved.',
    jsonb_build_object(
        'migrated_at', NOW(),
        'source', 'blueprint_phases, blueprint_tasks',
        'migration_script', 'migrate_existing_data.sql'
    )
);

COMMIT;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

SELECT
    'unified_projects' as table_name,
    COUNT(*) as rows,
    COUNT(DISTINCT parent_project_id) as with_parent
FROM unified_projects
UNION ALL
SELECT
    'unified_tasks',
    COUNT(*),
    COUNT(DISTINCT project_id)
FROM unified_tasks
UNION ALL
SELECT
    'archie_project_awareness',
    COUNT(*),
    0
FROM archie_project_awareness
UNION ALL
SELECT
    'archie_config_history',
    COUNT(*),
    0
FROM archie_config_history;
