-- 173_deploy_capabilities.sql
-- Seeds deploy_static + deploy_vps skills on B.A.S.E. (id=139)
-- Part of Autonomous Deploy Pipeline (Project #292, 2026-04-28)

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES
    (139, 'deploy_static', 5, NULL),
    (139, 'deploy_vps',    5, NULL)
ON CONFLICT (agent_id, skill_name) DO UPDATE
    SET proficiency_level = EXCLUDED.proficiency_level;
