-- Migration 389: F.A.C.T. lowercase dispatch skills + A.U.R.O.R.A. skills
--
-- Problem: F.A.C.T. (id=48) had only PascalCase skills from GitHub ingestion
-- ("Content Writing", "Blog Creation" etc). The dispatcher checks for lowercase
-- capability strings ("content_writing", "blog_creation") from CAPABILITY_DEPARTMENT_MAP.
-- These never matched → content_writing/news_writing dispatches hit the floor fallback.
--
-- news_writing and editorial had NO active agent with those skills at all.
-- A.U.R.O.R.A. (id=362) was deployed with zero skills — also hitting floor fallback.

-- F.A.C.T. (id=48): add canonical lowercase skill aliases
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
VALUES
  (48, 'content_writing',       'content', 5),
  (48, 'news_writing',          'content', 5),
  (48, 'editorial',             'content', 5),
  (48, 'blog_creation',         'content', 4),
  (48, 'ghostwriting',          'content', 4),
  (48, 'narrative_development', 'content', 3)
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = EXCLUDED.proficiency_level,
      skill_category    = EXCLUDED.skill_category;

-- A.U.R.O.R.A. (id=362): general news utility agent — primary news_writing/editorial,
-- secondary content_writing backup
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
VALUES
  (362, 'news_writing',    'content', 4),
  (362, 'editorial',       'content', 4),
  (362, 'content_writing', 'content', 3),
  (362, 'data_ingestion',  'data',    4)
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = EXCLUDED.proficiency_level,
      skill_category    = EXCLUDED.skill_category;
