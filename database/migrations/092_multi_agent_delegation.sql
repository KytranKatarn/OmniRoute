-- Migration 092: Multi-Agent Delegation
-- Phase 7: Multi-Agent Orchestration
-- Adds delegation_tasks table for tracking sub-task decomposition and execution

CREATE TABLE IF NOT EXISTS delegation_tasks (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES orchestration_sessions(id),
    parent_message TEXT NOT NULL,
    sub_task_index INTEGER NOT NULL,
    sub_task_description TEXT NOT NULL,
    assigned_agent_id INTEGER REFERENCES agents(id),
    assigned_station TEXT,
    model_used TEXT,
    status TEXT DEFAULT 'pending',  -- pending, running, completed, failed
    response TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_delegation_session ON delegation_tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_delegation_status ON delegation_tasks(status);

-- Update orchestration_steps check constraint to include new step types
ALTER TABLE orchestration_steps DROP CONSTRAINT IF EXISTS orchestration_steps_step_type_check;
ALTER TABLE orchestration_steps ADD CONSTRAINT orchestration_steps_step_type_check
    CHECK (step_type IN (
        'intent_parse', 'route_decision', 'agent_select', 'iaae_check',
        'welfare_check', 'gpu_check', 'execute', 'fallback', 'team_action',
        'param_extraction', 'joint_init', 'joint_session',
        'decompose', 'delegate', 'synthesize'
    ));
