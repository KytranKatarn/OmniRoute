-- 456_route_legacy_loops_ai_owner.sql
-- Grant the AI capability-owners the skills they need so the legacy background loops
-- (knowledge_analysis, research_synthesis) attribute their inference to a budgeted AI
-- agent instead of a legacy INTERNAL persona (Nexus/Oracle, Sage). Those personas are
-- worker_type='internal' → invisible to the AI budget/welfare/K.I.N. accounting, so
-- their real inference floated unattributed (~1.2M + 65k tok/30d). Pairs with the
-- CAPABILITY_SPECIALIST_MAP entries (department_coordinator.py) + the translate pin
-- swap Amina→R.O.S.E.T.T.A. (translation_scanners/generator.py). Idempotent.
--
-- D.A.R.W.I.N. (140, R&D AI director) has NO research_synthesis skill — Sage (33,
-- internal) monopolizes it. Without this grant, score_agent's -1.0 unskilled penalty
-- cancels the +0.75 specialist bonus, so the specialist-map entry alone can't win.
INSERT INTO agent_skills (id, agent_id, skill_name, skill_category, proficiency_level, notes, created_at, updated_at)
SELECT gen_random_uuid(), 140, 'research_synthesis',
       (SELECT skill_category FROM agent_skills WHERE skill_name = 'research_synthesis' LIMIT 1),
       5,
       'Granted so the R&D AI director owns research_synthesis (was Sage/internal-only) — migration 456',
       NOW(), NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM agent_skills WHERE agent_id = 140 AND skill_name = 'research_synthesis'
);

-- W.A.T.C.H. (152, Analytics AI) as an AI backup for knowledge_analysis, so a
-- S.P.E.C.T.R.A. rest window routes to an AI peer rather than back to the internal
-- Nexus/Oracle rows. S.P.E.C.T.R.A. (137) already holds knowledge_analysis lvl5.
INSERT INTO agent_skills (id, agent_id, skill_name, skill_category, proficiency_level, notes, created_at, updated_at)
SELECT gen_random_uuid(), 152, 'knowledge_analysis',
       (SELECT skill_category FROM agent_skills WHERE skill_name = 'knowledge_analysis' LIMIT 1),
       4,
       'AI backup for knowledge_analysis so S.P.E.C.T.R.A.-rest stays AI-owned (not internal Nexus/Oracle) — migration 456',
       NOW(), NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM agent_skills WHERE agent_id = 152 AND skill_name = 'knowledge_analysis'
);
