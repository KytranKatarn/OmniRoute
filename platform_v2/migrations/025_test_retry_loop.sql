-- Migration 025: Test Retry Loop + Contractor Escalation + Agent Personality
-- Created: 2026-01-14
-- Purpose: Support automated test-retry workflow with contractor escalation and fluid chat

-- ============================================================================
-- PART 1: Enhancement to improvement_proposals for test-retry tracking
-- ============================================================================

-- Test-specific retry count (separate from general retry_count)
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS test_retry_count INTEGER DEFAULT 0;

COMMENT ON COLUMN improvement_proposals.test_retry_count IS 'Number of times tests have been retried (max 3 before escalation)';

-- Detailed failure context for smarter retries
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS test_failure_context JSONB;

COMMENT ON COLUMN improvement_proposals.test_failure_context IS 'Detailed test failure info: error messages, stack traces, failed tests list';

-- Granular escalation status (more detailed than boolean escalated_to_contractor)
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS escalation_status VARCHAR(50) DEFAULT 'none';

COMMENT ON COLUMN improvement_proposals.escalation_status IS 'Escalation state: none, contractor_consulting, human_reviewing, human_only';

-- Store contractor's proposed fix
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS contractor_proposal JSONB;

COMMENT ON COLUMN improvement_proposals.contractor_proposal IS 'Contractor AI proposed fix: code changes, explanation, confidence score';

-- Which contractor agent is consulting
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS contractor_agent_id INTEGER REFERENCES agents(id);

COMMENT ON COLUMN improvement_proposals.contractor_agent_id IS 'ID of the contractor agent assigned for consultation';

-- Add constraint for valid escalation statuses
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'valid_escalation_status'
    ) THEN
        ALTER TABLE improvement_proposals
        ADD CONSTRAINT valid_escalation_status
        CHECK (escalation_status IN ('none', 'contractor_consulting', 'human_reviewing', 'human_only', 'resolved'));
    END IF;
END $$;

-- Index for querying escalated proposals
CREATE INDEX IF NOT EXISTS idx_proposals_escalation_status
ON improvement_proposals(escalation_status)
WHERE escalation_status != 'none';

-- ============================================================================
-- PART 2: Agent personality and chat system
-- ============================================================================

-- Personality prompt (distinct from system_prompt - this is for chat persona)
ALTER TABLE agents
ADD COLUMN IF NOT EXISTS personality_prompt TEXT;

COMMENT ON COLUMN agents.personality_prompt IS 'Chat personality: tone, quirks, communication style for fluid conversations';

-- Communication style enum
ALTER TABLE agents
ADD COLUMN IF NOT EXISTS communication_style VARCHAR(50) DEFAULT 'professional';

COMMENT ON COLUMN agents.communication_style IS 'Style: formal, casual, technical, friendly, professional';

-- Memory context for persistent conversation awareness
ALTER TABLE agents
ADD COLUMN IF NOT EXISTS memory_context JSONB DEFAULT '{}';

COMMENT ON COLUMN agents.memory_context IS 'Interaction history, learned preferences, past conversation context';

-- Work history summary (for context in conversations)
ALTER TABLE agents
ADD COLUMN IF NOT EXISTS work_history_summary JSONB DEFAULT '{}';

COMMENT ON COLUMN agents.work_history_summary IS 'Summary of past proposals, success patterns, expertise demonstrated';

-- Add constraint for communication styles
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'valid_communication_style'
    ) THEN
        ALTER TABLE agents
        ADD CONSTRAINT valid_communication_style
        CHECK (communication_style IN ('formal', 'casual', 'technical', 'friendly', 'professional'));
    END IF;
END $$;

-- ============================================================================
-- PART 3: Queue management table
-- ============================================================================

-- Track proposal processing queue (strict one-at-a-time)
CREATE TABLE IF NOT EXISTS proposal_queue (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    queue_position INTEGER NOT NULL,
    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    queue_status VARCHAR(20) DEFAULT 'queued',
    priority_boost INTEGER DEFAULT 0,
    CONSTRAINT valid_queue_status CHECK (queue_status IN ('queued', 'processing', 'completed', 'cancelled', 'failed'))
);

COMMENT ON TABLE proposal_queue IS 'Strict queue for proposal processing - only one proposal processes at a time';

CREATE INDEX IF NOT EXISTS idx_queue_status ON proposal_queue(queue_status);
CREATE INDEX IF NOT EXISTS idx_queue_position ON proposal_queue(queue_position) WHERE queue_status = 'queued';
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_active ON proposal_queue(proposal_id) WHERE queue_status IN ('queued', 'processing');

-- ============================================================================
-- PART 4: Chat messages table for fluid conversations
-- ============================================================================

-- Real-time chat messages for proposal discussions
CREATE TABLE IF NOT EXISTS proposal_chat_messages (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL, -- 'human', 'agent', 'contractor', 'system'
    sender_id INTEGER, -- agent_id or user_id depending on sender_type
    sender_name VARCHAR(100),
    content TEXT NOT NULL,
    message_type VARCHAR(20) DEFAULT 'text', -- 'text', 'code', 'proposal', 'action'
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE,
    CONSTRAINT valid_sender_type CHECK (sender_type IN ('human', 'agent', 'contractor', 'system'))
);

COMMENT ON TABLE proposal_chat_messages IS 'Fluid chat messages for proposal discussions between humans and AI agents';

CREATE INDEX IF NOT EXISTS idx_chat_proposal ON proposal_chat_messages(proposal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_unread ON proposal_chat_messages(proposal_id, is_read) WHERE is_read = FALSE;

-- ============================================================================
-- PART 5: Contractor consultation tracking
-- ============================================================================

-- Track contractor consultations
CREATE TABLE IF NOT EXISTS contractor_consultations (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    contractor_id INTEGER NOT NULL REFERENCES agents(id),
    consultation_status VARCHAR(30) DEFAULT 'pending',
    request_prompt TEXT,
    response_content TEXT,
    proposed_code TEXT,
    confidence_score NUMERIC(3,2),
    tokens_used INTEGER,
    cost_estimate NUMERIC(10,4),
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    applied_at TIMESTAMP,
    outcome VARCHAR(30), -- 'applied', 'rejected', 'modified', 'failed'
    human_feedback TEXT,
    CONSTRAINT valid_consultation_status CHECK (consultation_status IN ('pending', 'in_progress', 'completed', 'failed', 'timeout'))
);

COMMENT ON TABLE contractor_consultations IS 'Track each contractor consultation attempt for escalated proposals';

CREATE INDEX IF NOT EXISTS idx_consultation_proposal ON contractor_consultations(proposal_id);
CREATE INDEX IF NOT EXISTS idx_consultation_contractor ON contractor_consultations(contractor_id);
CREATE INDEX IF NOT EXISTS idx_consultation_status ON contractor_consultations(consultation_status);

-- ============================================================================
-- PART 6: Update default personality prompts for existing contractors
-- ============================================================================

-- Set default personality prompts for contractor agents
UPDATE agents
SET personality_prompt = CASE
    WHEN api_provider = 'anthropic' THEN
        'You are Claude, a thoughtful and thorough contractor. You explain your reasoning clearly and consider edge cases. You prefer elegant solutions over quick fixes.'
    WHEN api_provider = 'openai' THEN
        'You are GPT, a versatile contractor with broad knowledge. You provide structured, well-organized solutions and are good at breaking down complex problems.'
    WHEN api_provider = 'google' THEN
        'You are Gemini, an analytical contractor who excels at research and documentation. You provide detailed explanations and reference best practices.'
    WHEN api_provider = 'x-ai' THEN
        'You are Grok, a direct and efficient contractor. You cut through complexity to find practical solutions quickly. You have a slightly informal style.'
    ELSE NULL
END,
communication_style = CASE
    WHEN api_provider = 'anthropic' THEN 'professional'
    WHEN api_provider = 'openai' THEN 'formal'
    WHEN api_provider = 'google' THEN 'technical'
    WHEN api_provider = 'x-ai' THEN 'casual'
    ELSE 'professional'
END
WHERE worker_type = 'contract'
AND api_provider IS NOT NULL
AND personality_prompt IS NULL;

-- ============================================================================
-- PART 7: Helper function for queue management
-- ============================================================================

-- Function to get next queue position
CREATE OR REPLACE FUNCTION get_next_queue_position()
RETURNS INTEGER AS $$
DECLARE
    next_pos INTEGER;
BEGIN
    SELECT COALESCE(MAX(queue_position), 0) + 1
    INTO next_pos
    FROM proposal_queue
    WHERE queue_status IN ('queued', 'processing');
    RETURN next_pos;
END;
$$ LANGUAGE plpgsql;

-- Function to check if queue is available (no active processing)
CREATE OR REPLACE FUNCTION is_queue_available()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN NOT EXISTS (
        SELECT 1 FROM proposal_queue WHERE queue_status = 'processing'
    );
END;
$$ LANGUAGE plpgsql;

-- Function to get active processing proposal
CREATE OR REPLACE FUNCTION get_active_processing_proposal()
RETURNS TABLE(proposal_id INTEGER, started_at TIMESTAMP) AS $$
BEGIN
    RETURN QUERY
    SELECT pq.proposal_id, pq.started_at
    FROM proposal_queue pq
    WHERE pq.queue_status = 'processing'
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Migration complete
-- ============================================================================

-- Log migration
INSERT INTO knowledge_base (
    title,
    content,
    entry_type,
    source_type,
    importance,
    tags,
    created_at
) VALUES (
    'Migration 025: Test Retry Loop + Contractor Escalation',
    'Added test_retry_count, test_failure_context, escalation_status, contractor_proposal to improvement_proposals. Added personality_prompt, communication_style, memory_context to agents. Created proposal_queue, proposal_chat_messages, contractor_consultations tables.',
    'improvement',
    'migration',
    0.7,
    ARRAY['database', 'migration', 'improvements', 'contractors', 'chat'],
    CURRENT_TIMESTAMP
) ON CONFLICT DO NOTHING;
