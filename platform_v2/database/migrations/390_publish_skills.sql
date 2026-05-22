-- Migration 390: P.U.B.L.I.S.H. lowercase canonical skills
-- P.U.B.L.I.S.H. (id=58) had 22 PascalCase skills from GitHub ingestion
-- but zero lowercase dispatch-compatible skills → always floor fallback.

INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
VALUES
  (58, 'content_writing',       'content', 3),
  (58, 'editorial',             'content', 4),
  (58, 'metadata_enrichment',   'content', 4),
  (58, 'content_classification','content', 3)
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = EXCLUDED.proficiency_level,
      skill_category    = EXCLUDED.skill_category;
