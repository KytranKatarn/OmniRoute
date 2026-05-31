-- Migration 410: E.T.H.O.S. ethics-analyst capabilities (task #3277)
--
-- E.T.H.O.S. (agent 336, "Ethical Transparency & Harmonization Oversight System",
-- Legal & Regulatory) already exists (ADR-001) but only carried compliance/summarize/
-- translate skills. This seeds the four ethics capabilities the dispatcher routes to
-- it via CAPABILITY_DEPARTMENT_MAP, so dispatch(capability='ethics_review'|...) selects
-- E.T.H.O.S. instead of falling back to Engineering.
--
-- welfare_audit is the ethics-oversight counterpart to K.I.N.'s welfare operations:
-- E.T.H.O.S. reviews K.I.N.'s welfare digest as an ethics matter (non-exploitative AI).
--
-- Idempotent: ON CONFLICT (agent_id, skill_name) refreshes proficiency.

INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, notes)
VALUES
    (336, 'ethics_review',     'governance', 5, 'Primary capability — ethical review of governance_audit_log + agent welfare.'),
    (336, 'creed_analysis',    'governance', 5, 'C.R.E.E.D. framework analysis: accountability/fairness/privacy/safety/transparency.'),
    (336, 'policy_assessment', 'governance', 4, 'Assess platform actions against AI-ethics policy (EU AI Act, Montreal Declaration, PIPEDA).'),
    (336, 'welfare_audit',     'governance', 4, 'Ethics oversight of agent welfare — consumes K.I.N. welfare digest.')
ON CONFLICT (agent_id, skill_name)
DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    notes             = EXCLUDED.notes,
    updated_at        = NOW();
