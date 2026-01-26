-- ============================================================================
-- Migration 006: Agent Collaboration System
-- Date: 2026-01-01
-- Purpose: Enable multi-agent discussions and collaborative proposal evaluation
-- ============================================================================

-- Table 1: Agent Discussion Sessions
-- Stores discussion sessions where agents collaborate on proposals
CREATE TABLE IF NOT EXISTS agent_discussions (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    topic VARCHAR(255),
    description TEXT,
    facilitator_id INTEGER REFERENCES agents(id),  -- Usually A.R.C.H.I.E.
    status VARCHAR(50) DEFAULT 'active',  -- 'active', 'consensus_reached', 'escalated', 'closed'
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    consensus_reached BOOLEAN DEFAULT FALSE,
    consensus_score DECIMAL(3,2),  -- 0.00 to 1.00 (agreement level)
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 2: Agent Discussion Messages
-- Individual contributions from each agent in a discussion
CREATE TABLE IF NOT EXISTS agent_discussion_messages (
    id SERIAL PRIMARY KEY,
    discussion_id INTEGER REFERENCES agent_discussions(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES agents(id),
    message_type VARCHAR(50),  -- 'analysis', 'recommendation', 'concern', 'approval', 'question'
    message TEXT,
    confidence_score DECIMAL(3,2),  -- 0.00 to 1.00 (agent's confidence in their input)
    supporting_data JSONB,  -- Code analysis, metrics, etc.
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 3: Proposal Evaluations
-- Each agent's formal evaluation of a proposal
CREATE TABLE IF NOT EXISTS proposal_evaluations (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    discussion_id INTEGER REFERENCES agent_discussions(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES agents(id),
    role VARCHAR(50),  -- 'lead', 'reviewer', 'specialist'
    recommendation VARCHAR(50),  -- 'approve', 'reject', 'needs_changes', 'needs_testing'
    confidence_level DECIMAL(3,2),  -- 0.00 to 1.00
    risk_assessment VARCHAR(50),  -- 'low', 'medium', 'high', 'critical'
    estimated_effort VARCHAR(50),  -- '1-2h', '2-4h', '1-2d', etc.
    technical_notes TEXT,
    manager_summary TEXT,  -- Manager-friendly explanation
    concerns TEXT[],  -- Array of concern strings
    benefits TEXT[],  -- Array of benefit strings
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(proposal_id, agent_id)
);

-- Table 4: Team Consensus
-- Final consensus decision for a proposal
CREATE TABLE IF NOT EXISTS team_consensus (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    discussion_id INTEGER REFERENCES agent_discussions(id) ON DELETE CASCADE,
    final_recommendation VARCHAR(50),  -- 'approved', 'rejected', 'needs_revision'
    consensus_score DECIMAL(3,2),  -- 0.00 to 1.00 (level of agreement)
    participating_agents INTEGER[],  -- Array of agent IDs
    approval_count INTEGER,
    rejection_count INTEGER,
    abstain_count INTEGER,
    key_benefits TEXT[],
    key_risks TEXT[],
    implementation_plan TEXT,
    estimated_total_effort VARCHAR(50),
    priority_recommendation VARCHAR(50),
    created_by INTEGER REFERENCES agents(id),  -- Usually A.R.C.H.I.E.
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_discussions_proposal ON agent_discussions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_discussions_status ON agent_discussions(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_discussion_messages_discussion ON agent_discussion_messages(discussion_id, created_at);
CREATE INDEX IF NOT EXISTS idx_discussion_messages_agent ON agent_discussion_messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_proposal ON proposal_evaluations(proposal_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_agent ON proposal_evaluations(agent_id);
CREATE INDEX IF NOT EXISTS idx_consensus_proposal ON team_consensus(proposal_id);

-- Add new columns to improvement_proposals for collaboration tracking
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS discussion_id INTEGER REFERENCES agent_discussions(id),
ADD COLUMN IF NOT EXISTS consensus_id INTEGER REFERENCES team_consensus(id),
ADD COLUMN IF NOT EXISTS collaboration_enabled BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS team_recommendation VARCHAR(50);

-- Comments for documentation
COMMENT ON TABLE agent_discussions IS 'Stores multi-agent discussion sessions for proposal evaluation';
COMMENT ON TABLE agent_discussion_messages IS 'Individual agent contributions during discussions';
COMMENT ON TABLE proposal_evaluations IS 'Formal evaluations from each agent on a proposal';
COMMENT ON TABLE team_consensus IS 'Final team consensus decision on proposals';
COMMENT ON COLUMN proposal_evaluations.manager_summary IS 'Non-technical summary for management review';
COMMENT ON COLUMN proposal_evaluations.technical_notes IS 'Detailed technical analysis for developers';
