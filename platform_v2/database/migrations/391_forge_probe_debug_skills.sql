-- Migration 391: F.O.R.G.E. debug skill + P.R.O.B.E. engineering skills
--
-- F.O.R.G.E. (Engineering director) had code/code_review but not debug →
-- 'debug' capability had zero active Engineering agent coverage → floor fallback.
--
-- P.R.O.B.E. (Platform Reliability, Observation, Browser-testing & Evaluation)
-- had zero agent_skills entries at all.

-- F.O.R.G.E.: add debug
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
SELECT a.id, 'debug', 'engineering', 5 FROM agents a WHERE a.name = 'F.O.R.G.E.'
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = 5, skill_category = 'engineering';

-- P.R.O.B.E.: seed engineering skills (P.R.O.B.E. = platform reliability/QA)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
SELECT a.id, s.skill_name, 'engineering', s.lvl
FROM agents a,
     (VALUES ('debug', 5), ('code_review', 4), ('code', 3), ('general', 3)) s(skill_name, lvl)
WHERE a.name = 'P.R.O.B.E.'
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = EXCLUDED.proficiency_level,
      skill_category    = EXCLUDED.skill_category;
