-- Migration 021: Conversation Triage System
-- Phase 42: Knowledge extraction pipeline for Claude Code conversations
-- Created: January 16, 2026

-- ============================================================================
-- CONVERSATION TRIAGE QUEUE
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversation_triage_queue (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES conversation_sessions(id) ON DELETE SET NULL,

    -- Classification
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'skipped')),
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10), -- 10 = highest

    -- Assignment
    assigned_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,

    -- Classification results
    primary_topic VARCHAR(100),
    conversation_phase VARCHAR(50), -- planning, coding, debugging, reviewing, deploying
    urgency_score DECIMAL(3,2) DEFAULT 0.5,

    -- Extraction results (JSONB for flexibility)
    classification JSONB DEFAULT '{}',
    extractions JSONB DEFAULT '{}', -- {errors: [], snippets: [], insights: []}

    -- Knowledge entries created from this triage
    created_knowledge_ids INTEGER[] DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,

    -- Processing metadata
    processing_duration_ms INTEGER,
    error_message TEXT
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_triage_status ON conversation_triage_queue(status);
CREATE INDEX IF NOT EXISTS idx_triage_priority ON conversation_triage_queue(priority DESC);
CREATE INDEX IF NOT EXISTS idx_triage_created ON conversation_triage_queue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_triage_conversation ON conversation_triage_queue(conversation_id);

-- ============================================================================
-- EXTRACTED KNOWLEDGE TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS triage_extractions (
    id SERIAL PRIMARY KEY,
    triage_id INTEGER REFERENCES conversation_triage_queue(id) ON DELETE CASCADE,

    extraction_type VARCHAR(30) NOT NULL CHECK (extraction_type IN ('error', 'code_snippet', 'insight', 'decision', 'todo')),

    -- Extracted content
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,

    -- Metadata
    language VARCHAR(30), -- For code snippets
    severity VARCHAR(20), -- For errors (critical, high, medium, low)
    confidence_score DECIMAL(3,2) DEFAULT 0.8,

    -- Reference to created knowledge_base entry (if promoted)
    knowledge_base_id INTEGER REFERENCES knowledge_base(id) ON DELETE SET NULL,
    promoted_at TIMESTAMP WITH TIME ZONE,

    -- Raw extraction data
    raw_extraction JSONB DEFAULT '{}',

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_extractions_triage ON triage_extractions(triage_id);
CREATE INDEX IF NOT EXISTS idx_extractions_type ON triage_extractions(extraction_type);

-- ============================================================================
-- TRIAGE STATISTICS VIEW
-- ============================================================================

CREATE OR REPLACE VIEW triage_stats AS
SELECT
    status,
    COUNT(*) as count,
    AVG(priority) as avg_priority,
    AVG(urgency_score) as avg_urgency,
    MIN(created_at) as oldest,
    MAX(processed_at) as last_processed
FROM conversation_triage_queue
GROUP BY status;

-- ============================================================================
-- EXTRACTION STATISTICS VIEW
-- ============================================================================

CREATE OR REPLACE VIEW extraction_stats AS
SELECT
    extraction_type,
    COUNT(*) as total,
    COUNT(knowledge_base_id) as promoted_count,
    AVG(confidence_score) as avg_confidence,
    MAX(created_at) as last_created
FROM triage_extractions
GROUP BY extraction_type;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to queue a conversation for triage
CREATE OR REPLACE FUNCTION queue_for_triage(
    p_conversation_id INTEGER,
    p_session_id INTEGER DEFAULT NULL,
    p_priority INTEGER DEFAULT 5
) RETURNS INTEGER AS $$
DECLARE
    v_triage_id INTEGER;
BEGIN
    INSERT INTO conversation_triage_queue (conversation_id, session_id, priority)
    VALUES (p_conversation_id, p_session_id, p_priority)
    RETURNING id INTO v_triage_id;

    RETURN v_triage_id;
END;
$$ LANGUAGE plpgsql;

-- Function to promote extraction to knowledge_base
CREATE OR REPLACE FUNCTION promote_extraction(
    p_extraction_id INTEGER,
    p_importance_score DECIMAL DEFAULT 0.85
) RETURNS INTEGER AS $$
DECLARE
    v_extraction RECORD;
    v_knowledge_id INTEGER;
    v_knowledge_type VARCHAR(30);
BEGIN
    SELECT * INTO v_extraction FROM triage_extractions WHERE id = p_extraction_id;

    IF v_extraction IS NULL THEN
        RAISE EXCEPTION 'Extraction % not found', p_extraction_id;
    END IF;

    -- Map extraction type to knowledge_base type
    v_knowledge_type := CASE v_extraction.extraction_type
        WHEN 'error' THEN 'mistake_learned'
        WHEN 'code_snippet' THEN 'code_snippet'
        WHEN 'insight' THEN 'vault_note'
        WHEN 'decision' THEN 'improvement'
        ELSE 'conversation_memory'
    END;

    -- Insert into knowledge_base
    INSERT INTO knowledge_base (title, content, knowledge_type, category, importance_score, source_type, source_id)
    VALUES (
        v_extraction.title,
        v_extraction.content,
        v_knowledge_type,
        'Triage/' || v_extraction.extraction_type,
        p_importance_score,
        'triage_extraction',
        'extraction-' || p_extraction_id
    )
    RETURNING id INTO v_knowledge_id;

    -- Update extraction with reference
    UPDATE triage_extractions
    SET knowledge_base_id = v_knowledge_id, promoted_at = NOW()
    WHERE id = p_extraction_id;

    RETURN v_knowledge_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SEED: Create knowledge extraction agents
-- ============================================================================

-- Check if agents already exist before inserting
DO $$
BEGIN
    -- Knowledge Curator
    IF NOT EXISTS (SELECT 1 FROM agents WHERE name = 'Knowledge Curator') THEN
        INSERT INTO agents (name, role, department, model, status, personality_traits, skills)
        VALUES (
            'Knowledge Curator',
            'Conversation Triage Specialist',
            'Knowledge Management',
            'deepseek-coder-v2:16b',
            'active',
            '{"analytical": 0.9, "thorough": 0.85, "organized": 0.95}',
            ARRAY['classification', 'triage', 'knowledge_organization', 'pattern_recognition']
        );
    END IF;

    -- Error Analyst
    IF NOT EXISTS (SELECT 1 FROM agents WHERE name = 'Error Analyst') THEN
        INSERT INTO agents (name, role, department, model, status, personality_traits, skills)
        VALUES (
            'Error Analyst',
            'Mistake & Error Extraction',
            'Knowledge Management',
            'qwen2.5-coder:7b',
            'active',
            '{"precise": 0.95, "detail_oriented": 0.9, "solution_focused": 0.85}',
            ARRAY['error_analysis', 'debugging', 'root_cause_analysis', 'solution_extraction']
        );
    END IF;

    -- Code Archivist
    IF NOT EXISTS (SELECT 1 FROM agents WHERE name = 'Code Archivist') THEN
        INSERT INTO agents (name, role, department, model, status, personality_traits, skills)
        VALUES (
            'Code Archivist',
            'Code Snippet Extraction',
            'Knowledge Management',
            'qwen2.5-coder:7b',
            'active',
            '{"meticulous": 0.9, "technical": 0.95, "organized": 0.85}',
            ARRAY['code_analysis', 'pattern_extraction', 'documentation', 'code_categorization']
        );
    END IF;

    -- Learning Synthesizer
    IF NOT EXISTS (SELECT 1 FROM agents WHERE name = 'Learning Synthesizer') THEN
        INSERT INTO agents (name, role, department, model, status, personality_traits, skills)
        VALUES (
            'Learning Synthesizer',
            'Insight & Decision Extraction',
            'Knowledge Management',
            'deepseek-coder-v2:16b',
            'active',
            '{"insightful": 0.95, "strategic": 0.85, "analytical": 0.9}',
            ARRAY['insight_extraction', 'decision_analysis', 'synthesis', 'knowledge_creation']
        );
    END IF;
END $$;

-- Assign new agents to Consciousness station
DO $$
DECLARE
    v_consciousness_id INTEGER;
    v_agent_id INTEGER;
BEGIN
    -- Get Consciousness station ID
    SELECT id INTO v_consciousness_id FROM bridge_stations WHERE station_code = 'CONSCIOUSNESS';

    IF v_consciousness_id IS NOT NULL THEN
        -- Assign Knowledge Management agents to Consciousness
        FOR v_agent_id IN
            SELECT id FROM agents WHERE department = 'Knowledge Management'
        LOOP
            -- Insert if not already assigned
            INSERT INTO station_assignments (agent_id, station_id, assigned_at)
            VALUES (v_agent_id, v_consciousness_id, NOW())
            ON CONFLICT (agent_id, station_id) DO NOTHING;
        END LOOP;
    END IF;
END $$;

-- ============================================================================
-- DONE
-- ============================================================================
SELECT 'Migration 021: Conversation Triage System - COMPLETE' as status;
