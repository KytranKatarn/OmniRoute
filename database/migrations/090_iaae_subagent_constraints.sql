-- 090: IAAE Sub-Agent Governance Constraints
-- Part of Phase 2: ARCHIE creating/managing agents via Chat

-- Add sub-agent governance constraints
INSERT INTO ethics_constraints (constraint_type, name, description, severity, enforcement_action, is_active)
VALUES
    ('autonomy', 'sub_agent_creation_limit',
     'Maximum number of sub-agents any single agent can create',
     'warning', 'log_and_warn', TRUE),
    ('autonomy', 'sub_agent_generation_limit',
     'Maximum depth of agent creation chain (prevents recursive spawning)',
     'mandatory', 'block', TRUE),
    ('workload', 'sub_agent_token_budget',
     'Daily token budget enforcement for sub-agents',
     'warning', 'log_and_warn', TRUE),
    ('autonomy', 'agent_creation_approval',
     'Require human approval before creating new agents via chat',
     'advisory', 'log_and_warn', TRUE)
ON CONFLICT DO NOTHING;
