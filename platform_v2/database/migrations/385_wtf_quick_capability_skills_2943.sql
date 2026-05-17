-- 385_wtf_quick_capability_skills_2943.sql
-- Phase A of #2943 two-tier LLM. Seeds the new *_quick capabilities as
-- skills on the existing News & Media agents (B.I.A.S./V.E.R.I.F.Y./L.O.C.A.L.).
-- Without these rows, the dispatcher's skill-first router has nothing to
-- match on for the new capabilities registered in CAPABILITY_DEPARTMENT_MAP.
--
-- See docs/two-tier-llm-design.md in the what-the-fact repo for the full
-- design.
--
-- Idempotent — safe to re-run.

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, skill_category)
SELECT a.id, q.skill, q.lvl, 'news_media'
FROM agents a, (VALUES
  ('B.I.A.S.',     'bias_quick',      4),
  ('V.E.R.I.F.Y.', 'factcheck_quick', 4),
  ('L.O.C.A.L.',   'geo_quick',       4)
) AS q(agent_name, skill, lvl)
WHERE a.name = q.agent_name
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = EXCLUDED.proficiency_level;
