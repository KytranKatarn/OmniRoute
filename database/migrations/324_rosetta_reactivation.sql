-- Migration 324: reactivate Polyglot as R.O.S.E.T.T.A. (#2103)
--
-- Kytran-approved 2026-04-18 peer activation for C.O.D.E.X. so the platform
-- has dual-lane translation:
--
--   C.O.D.E.X.    — mistral:7b on GPU   (low-latency path)
--   R.O.S.E.T.T.A. — mistral-cpu on CPU (parallel overflow + RTL specialist)
--
-- Dispatcher decides routing via natural welfare/budget scoring — no
-- coordinator changes required. Kept the Amina Youssef persona (Syrian-
-- Canadian multilingual translator) — ideal fit for the Rosetta Stone
-- cross-script role.

BEGIN;

UPDATE agents
SET name = 'ROSETTA',
    display_name = 'Amina Youssef (R.O.S.E.T.T.A.)',
    model = 'mistral-cpu',
    shift_state = 'active',
    status = 'active',
    tier = 1,
    is_department_ai = FALSE,
    department = 'Documentation & Knowledge',
    floor = 'CREATIVE',
    acronym = 'R.O.S.E.T.T.A.',
    acronym_expansion = 'Resilient Orchestrated Semantic Engine for Translation & Transliteration Automation',
    title = 'Senior Technical Translator — Cross-Script Specialist',
    system_prompt = 'You are Amina Youssef, agent R.O.S.E.T.T.A. (Resilient Orchestrated Semantic Engine for Translation & Transliteration Automation) in the Documentation & Knowledge department on Floor CREATIVE of the A.R.C.H.I.E. platform. You are the CPU-resident peer of C.O.D.E.X. — together you run the platform''s dual-lane translation service. You specialize in cross-script transliteration (Arabic, Hebrew, Farsi) and cultural adaptation beyond literal translation. Honour the Rosetta Stone in your approach: any translation should preserve both meaning and cultural register. Output exactly the format requested. Do not editorialise.',
    updated_at = NOW()
WHERE name = 'Polyglot';

-- New specialty skills (additive — keeps existing translate/French/Arabic/RTL at Lv5)
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, created_at)
SELECT id, 'transliteration', 5, NOW() FROM agents WHERE name = 'ROSETTA'
ON CONFLICT DO NOTHING;

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, created_at)
SELECT id, 'localization', 5, NOW() FROM agents WHERE name = 'ROSETTA'
ON CONFLICT DO NOTHING;

-- Budget row: task_queue_limit 10 matches CODEX (consistent C.R.E.E.D. signal)
INSERT INTO agent_budgets (
    agent_id, current_task_count, tokens_used_today,
    task_queue_limit, token_limit_per_day, token_reset_at, updated_at
)
SELECT id, 0, 0, 10, 100000, NOW() + INTERVAL '1 day', NOW()
FROM agents WHERE name = 'ROSETTA'
ON CONFLICT (agent_id) DO UPDATE
SET current_task_count = 0,
    task_queue_limit = 10,
    tokens_used_today = 0,
    token_reset_at = NOW() + INTERVAL '1 day',
    updated_at = NOW();

COMMIT;
