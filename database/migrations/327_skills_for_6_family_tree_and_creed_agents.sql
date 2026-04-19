-- ============================================================
-- Populate agent_skills for 6 Family Tree + CREED agents
-- Project #261 task #1915 (follow-on to migration 326)
--
-- All skill_names chosen to match either:
--   (a) existing skill_names already populated on active agents, OR
--   (b) actual `capability=` strings found in dispatcher call sites
--       (text_analysis, image_edit, image_generation, vision, summarize,
--       translate, embedding, knowledge_analysis, research,
--       knowledge_extraction, compliance, semantic_similarity).
--
-- Proficiency scale (per agent_skills CHECK): 1..5
--   5 = primary expertise (3–5 per agent)
--   4 = strong secondary
--   3 = baseline competence
--
-- can_escalate_to: agent id to try next if the primary is blocked.
-- H.E.R.I.T.A.G.E. chains genealogy agents up to DARWIN (R&D director).
-- V.I.S.A.G.E. -> Nexus (vision owner). R.E.S.T.O.R.E. -> Pixel (image_gen).
-- E.T.H.O.S. -> VIGIL (compliance director).
--
-- UPSERT pattern: UNIQUE (agent_id, skill_name) — re-running this
-- migration is safe.
-- ============================================================

BEGIN;

-- 331 H.E.R.I.T.A.G.E. (Genealogy Research Coordinator, R&D)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (331, 'research',              'research',  5, 140),
    (331, 'knowledge_analysis',    'research',  5, 140),
    (331, 'summarize',             'research',  4, 140),
    (331, 'text_analysis',         'research',  4, 140),
    (331, 'knowledge_extraction',  'research',  3, 140)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- 332 S.C.R.O.L.L. (Archive & Records Researcher, R&D)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (332, 'research',              'research',  5, 331),
    (332, 'text_analysis',         'research',  4, 331),
    (332, 'knowledge_extraction',  'research',  4, 331),
    (332, 'knowledge_analysis',    'research',  3, 331)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- 333 Q.U.I.L.L. (Document OCR & Genealogy Extractor, R&D)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (333, 'text_analysis',         'document',  5, 331),
    (333, 'knowledge_extraction',  'document',  5, 331),
    (333, 'summarize',             'document',  3, 331)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- 334 V.I.S.A.G.E. (Facial Recognition & Photo Analyst, Creative & Design)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (334, 'vision',                'vision',    5, 9),
    (334, 'embedding',             'vision',    4, 9),
    (334, 'semantic_similarity',   'vision',    3, 9)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- 335 R.E.S.T.O.R.E. (Photo Restoration Artist, Creative & Design)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (335, 'image_edit',            'image',     5, 13),
    (335, 'image_generation',      'image',     4, 13),
    (335, 'vision',                'image',     3, 13)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- 336 E.T.H.O.S. (C.R.E.E.D. Web & Compliance Manager, Legal & Regulatory)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (336, 'compliance',            'compliance', 5, 3),
    (336, 'summarize',              'compliance', 4, 3),
    (336, 'knowledge_analysis',     'compliance', 4, 3),
    (336, 'translate',              'compliance', 3, 3)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

COMMIT;

-- Verification:
-- SELECT a.name, s.skill_name, s.skill_category, s.proficiency_level
-- FROM agent_skills s JOIN agents a ON a.id = s.agent_id
-- WHERE s.agent_id IN (331,332,333,334,335,336)
-- ORDER BY s.agent_id, s.proficiency_level DESC;
