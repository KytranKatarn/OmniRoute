-- Migration 012c: Link improvement_proposals with knowledge_base
-- Date: 2026-01-09
-- Purpose: Integrate improvements system with unified knowledge architecture
--
-- This migration:
-- 1. Links improvement_proposals to knowledge_base entries
-- 2. Enables improvements to leverage full knowledge context
-- 3. Creates improvement and mistake_learned entries in knowledge_base

-- ============================================================================
-- STEP 1: Extend improvement_proposals table
-- ============================================================================

-- Add knowledge_base reference for single primary knowledge entry
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS knowledge_entry_id INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL;

-- Add array of knowledge IDs for contextual knowledge
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS context_knowledge_ids INTEGER[];

-- Add fields to track what was learned from this improvement
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS learned_entry_id INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL;

-- Add status tracking
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS implementation_notes TEXT;

-- ============================================================================
-- STEP 2: Create indexes for performance
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_improvements_knowledge
    ON improvement_proposals(knowledge_entry_id);

CREATE INDEX IF NOT EXISTS idx_improvements_learned
    ON improvement_proposals(learned_entry_id);

-- GIN index for array search on context_knowledge_ids
CREATE INDEX IF NOT EXISTS idx_improvements_context_gin
    ON improvement_proposals USING GIN(context_knowledge_ids);

CREATE INDEX IF NOT EXISTS idx_improvements_status
    ON improvement_proposals(status, priority DESC);

-- ============================================================================
-- STEP 3: Create function to create improvement knowledge entry
-- ============================================================================

CREATE OR REPLACE FUNCTION create_improvement_knowledge_entry(
    p_proposal_id INTEGER,
    p_title TEXT,
    p_description TEXT,
    p_code_diff TEXT DEFAULT NULL,
    p_tags TEXT[] DEFAULT ARRAY[]::TEXT[]
)
RETURNS INTEGER AS $$
DECLARE
    new_kb_id INTEGER;
    proposal_data RECORD;
BEGIN
    -- Get proposal details
    SELECT * INTO proposal_data
    FROM improvement_proposals
    WHERE id = p_proposal_id;

    -- Create knowledge_base entry
    INSERT INTO knowledge_base (
        knowledge_type,
        title,
        content,
        category,
        tags,
        importance_score,
        memory_metadata,
        source_type,
        source_id,
        created_at,
        updated_at
    ) VALUES (
        'improvement',
        p_title,
        p_description || COALESCE(E'\n\n## Code Changes\n' || p_code_diff, ''),
        proposal_data.category,
        p_tags,
        0.90,  -- Improvements are high importance
        jsonb_build_object(
            'proposal_id', p_proposal_id,
            'status', proposal_data.status,
            'priority', proposal_data.priority,
            'created_at', proposal_data.created_at,
            'deployed_at', proposal_data.deployed_at
        ),
        'improvement_system',
        'proposal_' || p_proposal_id::text,
        NOW(),
        NOW()
    )
    RETURNING id INTO new_kb_id;

    -- Link back to proposal
    UPDATE improvement_proposals
    SET learned_entry_id = new_kb_id
    WHERE id = p_proposal_id;

    RETURN new_kb_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- STEP 4: Create function to create mistake_learned entry
-- ============================================================================

CREATE OR REPLACE FUNCTION create_mistake_learned_entry(
    p_title TEXT,
    p_error_message TEXT,
    p_solution TEXT,
    p_category VARCHAR(100) DEFAULT 'general',
    p_tags TEXT[] DEFAULT ARRAY['common-error']::TEXT[],
    p_severity VARCHAR(20) DEFAULT 'medium',
    p_context JSONB DEFAULT '{}'::JSONB
)
RETURNS INTEGER AS $$
DECLARE
    new_kb_id INTEGER;
    full_content TEXT;
BEGIN
    -- Build comprehensive content
    full_content := format(
        E'# Common Error: %s\n\n## Error Message\n```\n%s\n```\n\n## Solution\n%s\n\n## Severity\n%s\n\n## Context\n%s',
        p_title,
        p_error_message,
        p_solution,
        p_severity,
        jsonb_pretty(p_context)
    );

    -- Create knowledge_base entry
    INSERT INTO knowledge_base (
        knowledge_type,
        title,
        content,
        category,
        tags,
        importance_score,
        memory_metadata,
        source_type,
        source_id,
        created_at,
        updated_at
    ) VALUES (
        'mistake_learned',
        'Common Error: ' || p_title,
        full_content,
        p_category,
        p_tags || ARRAY[p_severity],
        0.95,  -- Mistakes are VERY high importance to prevent repetition
        jsonb_build_object(
            'severity', p_severity,
            'error_message', p_error_message,
            'solution', p_solution,
            'detected_at', NOW(),
            'context', p_context
        ),
        'mistake_detector',
        'mistake_' || md5(p_error_message),
        NOW(),
        NOW()
    )
    ON CONFLICT (knowledge_type, source_id) DO UPDATE
    SET access_count = knowledge_base.access_count + 1,
        last_accessed = NOW()
    RETURNING id INTO new_kb_id;

    RETURN new_kb_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- STEP 5: Create view for easy improvements querying
-- ============================================================================

CREATE OR REPLACE VIEW improvement_knowledge AS
SELECT
    ip.id as proposal_id,
    ip.title as proposal_title,
    ip.status,
    ip.priority,
    ip.category,
    ip.created_at as proposed_at,
    ip.deployed_at,
    kb.id as knowledge_id,
    kb.title as knowledge_title,
    kb.content as knowledge_content,
    kb.tags,
    kb.importance_score,
    kb.access_count,
    ip.context_knowledge_ids
FROM improvement_proposals ip
LEFT JOIN knowledge_base kb ON ip.learned_entry_id = kb.id
WHERE kb.knowledge_type = 'improvement' OR ip.learned_entry_id IS NULL
ORDER BY ip.created_at DESC;

-- ============================================================================
-- STEP 6: Create view for mistake learnings
-- ============================================================================

CREATE OR REPLACE VIEW mistake_learnings AS
SELECT
    id,
    title,
    content,
    category,
    tags,
    importance_score,
    access_count,
    last_accessed,
    memory_metadata->>'severity' as severity,
    memory_metadata->>'error_message' as error_message,
    memory_metadata->>'solution' as solution,
    created_at as learned_at
FROM knowledge_base
WHERE knowledge_type = 'mistake_learned'
ORDER BY importance_score DESC, access_count DESC, created_at DESC;

-- ============================================================================
-- STEP 7: Migrate existing deployed improvements to knowledge_base
-- ============================================================================

-- Create knowledge entries for successfully deployed improvements
DO $$
DECLARE
    proposal RECORD;
    new_kb_id INTEGER;
    migrated_count INTEGER := 0;
BEGIN
    FOR proposal IN
        SELECT * FROM improvement_proposals
        WHERE status = 'deployed'
          AND learned_entry_id IS NULL
          AND deployed_at IS NOT NULL
        ORDER BY deployed_at DESC
    LOOP
        -- Create knowledge entry
        new_kb_id := create_improvement_knowledge_entry(
            proposal.id,
            proposal.title,
            proposal.description,
            NULL,  -- No code diff stored in old data
            ARRAY['deployed', proposal.category]::TEXT[]
        );

        migrated_count := migrated_count + 1;
    END LOOP;

    RAISE NOTICE 'Migrated % deployed improvements to knowledge_base', migrated_count;
END $$;

-- ============================================================================
-- STEP 8: Create common mistake entries from known patterns
-- ============================================================================

-- Add common errors we've already encountered
DO $$
DECLARE
    kb_id INTEGER;
BEGIN
    -- Database column missing error
    kb_id := create_mistake_learned_entry(
        'Database Column Missing',
        'column "column_name" does not exist',
        E'Check the database schema and add missing columns via migration.\n\nSteps:\n1. Verify column exists in schema\n2. Create migration file if needed\n3. Run migration: docker exec archie_database psql -U archie -d archie -f migration.sql\n4. Restart application',
        'database_schema',
        ARRAY['database', 'schema', 'common-error', 'postgres'],
        'high',
        '{"common_cause": "Schema not updated after code changes", "prevention": "Always run migrations before deploying code"}'::JSONB
    );

    -- Circular import error
    kb_id := create_mistake_learned_entry(
        'Circular Import',
        'ImportError: cannot import name X from partially initialized module (most likely due to a circular import)',
        E'Refactor code to break the circular dependency.\n\nSolutions:\n1. Move shared code to a separate module\n2. Use import inside function instead of module level\n3. Restructure module hierarchy\n4. Use TYPE_CHECKING from typing module',
        'python_imports',
        ARRAY['python', 'imports', 'circular-dependency', 'common-error'],
        'high',
        '{"common_cause": "Modules importing each other", "prevention": "Design clear dependency hierarchy"}'::JSONB
    );

    -- Jinja2 syntax error
    kb_id := create_mistake_learned_entry(
        'Jinja2 Template Syntax Error',
        'TemplateSyntaxError: unexpected %',
        E'Use Jinja2 syntax, not other template languages.\n\nCorrect syntax:\n- Variables: {{ variable }}\n- Statements: {% if condition %} ... {% endif %}\n- Comments: {# comment #}\n\nDo NOT use:\n- ${{}}: This is wrong\n- $variable: This is shell syntax',
        'template_syntax',
        ARRAY['jinja2', 'flask', 'templates', 'common-error'],
        'medium',
        '{"common_cause": "Mixing template syntaxes", "prevention": "Always use Jinja2 syntax in Flask templates"}'::JSONB
    );

    -- Template not found error
    kb_id := create_mistake_learned_entry(
        'Flask Template Not Found',
        'jinja2.exceptions.TemplateNotFound',
        E'Ensure template path is correct.\n\nCommon fixes:\n1. Add "tools/" prefix for module templates: render_template(''tools/obsidian_vault.html'')\n2. Check template exists in /templates/ directory\n3. Verify file extension is .html\n4. Check for typos in filename',
        'flask_templates',
        ARRAY['flask', 'jinja2', 'templates', 'common-error'],
        'medium',
        '{"common_cause": "Incorrect template path", "prevention": "Use render_template with full path from /templates/"}'::JSONB
    );

    RAISE NOTICE 'Created 4 common mistake knowledge entries';
END $$;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    improvements_count INTEGER;
    mistakes_count INTEGER;
    linked_proposals INTEGER;
BEGIN
    SELECT COUNT(*) INTO improvements_count
    FROM knowledge_base WHERE knowledge_type = 'improvement';

    SELECT COUNT(*) INTO mistakes_count
    FROM knowledge_base WHERE knowledge_type = 'mistake_learned';

    SELECT COUNT(*) INTO linked_proposals
    FROM improvement_proposals WHERE learned_entry_id IS NOT NULL;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Migration 012c - Improvements Integration Complete';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Improvement knowledge entries: %', improvements_count;
    RAISE NOTICE 'Mistake learned entries: %', mistakes_count;
    RAISE NOTICE 'Proposals linked to knowledge: %', linked_proposals;
    RAISE NOTICE '';
    RAISE NOTICE 'New columns added to improvement_proposals:';
    RAISE NOTICE '  - knowledge_entry_id (single KB link)';
    RAISE NOTICE '  - context_knowledge_ids (contextual KB links)';
    RAISE NOTICE '  - learned_entry_id (learned KB entry)';
    RAISE NOTICE '  - implementation_notes (notes)';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions created:';
    RAISE NOTICE '  - create_improvement_knowledge_entry()';
    RAISE NOTICE '  - create_mistake_learned_entry()';
    RAISE NOTICE '';
    RAISE NOTICE 'Views created:';
    RAISE NOTICE '  - improvement_knowledge';
    RAISE NOTICE '  - mistake_learnings';
    RAISE NOTICE '=================================================';
END $$;

-- Show sample mistake learnings
SELECT
    title,
    category,
    array_length(tags, 1) as tag_count,
    importance_score,
    created_at
FROM mistake_learnings
ORDER BY importance_score DESC, created_at DESC;
