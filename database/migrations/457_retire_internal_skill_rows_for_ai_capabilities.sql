-- 457_retire_internal_skill_rows_for_ai_capabilities.sql
-- Completes "route legacy loops to the AI owner" (migration 456 + PR #2183). LIVE
-- verification showed the CAPABILITY_SPECIALIST_MAP bonus (+0.75) alone did NOT reliably
-- win: several legacy INTERNAL agents (Nexus/Oracle/Scout/Spark-Jr/Wordsmith for
-- knowledge_analysis, Sage for research_synthesis, Amina/Nexus/Oracle/Scout for translate;
-- all worker_type='internal') also hold these skills and — being fresh + low-util — out-score
-- a loaded/throttled AI owner. So knowledge_analysis still selected the internal Nexus and
-- its tokens stayed invisible to the AI budget/welfare/K.I.N. accounting.
--
-- Retire the internal skill rows for these 3 AI-analysis capabilities so the dispatcher can
-- only pick a BUDGETED AI agent (worker_type='ai'). Safe: knowledge_analysis has 9 AI
-- holders, translate 5, research_synthesis 1 (D.A.R.W.I.N., granted in 456) + wake-on-demand.
-- Internal agents remain the human-mirror workforce; they simply no longer advertise these
-- AI-dispatch capabilities. Idempotent. (Broader fix — excluding worker_type='internal' from
-- the dispatch candidate pool entirely — is a larger change tracked as a follow-up.)
DELETE FROM agent_skills
WHERE skill_name IN ('knowledge_analysis', 'research_synthesis', 'translate')
  AND agent_id IN (SELECT id FROM agents WHERE worker_type = 'internal');
