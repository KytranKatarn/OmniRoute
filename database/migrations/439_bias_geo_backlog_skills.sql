-- 439: seed bias_backlog + geo_backlog agent_skills (#4275)
--
-- The bias_backlog / geo_backlog capabilities had NO dedicated agent_skill, so the DHQ
-- cross-department skill fallback could not find the bias / geo pool. Combined with the
-- capabilities being absent from the coordinator CAPABILITY_DEPARTMENT_MAP, they defaulted
-- to Engineering & Technology -> the Codex contractor (model 'codex-cli') was selected for
-- bias work and 404'd (codex-cli is not an Ollama/cluster model).
--
-- Mirror the established fact_check_backlog pattern: give every agent that holds
-- bias_analysis / geo_extraction the matching *_backlog skill at the SAME proficiency,
-- so the backlog capability routes to exactly the production pool. Idempotent.

INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
SELECT agent_id, 'bias_backlog', skill_category, proficiency_level
FROM agent_skills
WHERE skill_name = 'bias_analysis'
ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level;

INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
SELECT agent_id, 'geo_backlog', skill_category, proficiency_level
FROM agent_skills
WHERE skill_name = 'geo_extraction'
ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level;
