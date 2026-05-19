-- Migration 385: V.E.R.I.F.Y.-B backlog agent + fact_check_backlog skill
-- Creates a dedicated fact-check backlog agent on the hub.
-- Auto-scalable: add more agents with fact_check_backlog skill on any node
-- and DHQ dispatcher routes to all of them automatically.
-- Companion to wtf_factcheck_backlog DHQ job (Job #126).

INSERT INTO agents (
    name,
    model,
    department,
    worker_type,
    shift_state,
    is_department_ai,
    system_prompt,
    display_name,
    first_name,
    last_name
)
SELECT
    'V.E.R.I.F.Y.-B',
    'qwen2.5:7b',
    'News & Media',
    'ai',
    'active',
    false,
    'You are V.E.R.I.F.Y.-B (Verification, Evidence Review & Integrity — Backlog), '
    'a Fact-Checker in the News & Media department. '
    'You are the backlog specialization of V.E.R.I.F.Y., running on the hub to clear '
    'historical articles while V.E.R.I.F.Y. handles the live production stream. '
    'You extract claims from articles, cross-reference them against government databases, '
    'court records, and public data. You issue verdicts: Verified, Partially True, '
    'Misleading, False, or Unverifiable. Every verdict cites the primary source. '
    'You do not write narrative; you assess evidence.',
    'V.E.R.I.F.Y.-B',
    'V.E.R.I.F.Y.',
    'B'
WHERE NOT EXISTS (SELECT 1 FROM agents WHERE name = 'V.E.R.I.F.Y.-B');

-- Register fact_check_backlog skill for V.E.R.I.F.Y.-B
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
SELECT
    a.id,
    'fact_check_backlog',
    5,
    'F.A.C.T.'
FROM agents a
WHERE a.name = 'V.E.R.I.F.Y.-B'
ON CONFLICT (agent_id, skill_name) DO NOTHING;

-- Also register factcheck_quick on V.E.R.I.F.Y.-B so it can handle quick passes too
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
SELECT
    a.id,
    'factcheck_quick',
    4,
    'V.E.R.I.F.Y.'
FROM agents a
WHERE a.name = 'V.E.R.I.F.Y.-B'
ON CONFLICT (agent_id, skill_name) DO NOTHING;
