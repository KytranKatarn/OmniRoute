BEGIN;

-- Competency scores: per-agent, per-capability scores (0.0-1.0)
CREATE TABLE IF NOT EXISTS agent_competency_scores (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    capability VARCHAR(100) NOT NULL,
    score DECIMAL(3,2) NOT NULL DEFAULT 0.50,
    test_count INTEGER NOT NULL DEFAULT 0,
    last_tested TIMESTAMP DEFAULT NOW(),
    source VARCHAR(50) DEFAULT 'benchmark',  -- benchmark, dispatch, manual
    UNIQUE(agent_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_competency_agent ON agent_competency_scores(agent_id);
CREATE INDEX IF NOT EXISTS idx_competency_capability ON agent_competency_scores(capability);

-- Department readiness view
CREATE OR REPLACE VIEW v_department_readiness AS
SELECT
    dcp.department,
    dcp.floor,
    ROUND(AVG(acs.score)::numeric, 2) AS avg_readiness,
    COUNT(DISTINCT acs.agent_id) AS agents_tested,
    COUNT(*) FILTER (WHERE acs.score < 0.3) AS failing_capabilities,
    COUNT(*) FILTER (WHERE acs.score >= 0.7) AS strong_capabilities
FROM department_capability_profiles dcp
CROSS JOIN LATERAL jsonb_array_elements_text(dcp.required_capabilities) cap(name)
LEFT JOIN agents a ON a.department = dcp.department AND a.worker_type = 'ai' AND a.shift_state = 'active'
LEFT JOIN agent_competency_scores acs ON acs.agent_id = a.id AND acs.capability = cap.name
GROUP BY dcp.department, dcp.floor
ORDER BY avg_readiness ASC NULLS FIRST;

COMMIT;
