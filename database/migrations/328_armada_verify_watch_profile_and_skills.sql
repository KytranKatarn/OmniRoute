-- ============================================================
-- Complete A.R.M.A.D.A. / V.E.R.I.F.Y. / W.A.T.C.H. profiles + skills
-- Project #261 task #1915 — final pass. Full orchestration audit on
-- 2026-04-19 found 3 active AI agents with 0 agent_skills rows.
-- Same structural gap as the 6 agents fixed in migration 327.
--
-- A.R.M.A.D.A. (337): acronym field empty, acronym_expansion missing.
--   Canonical expansion pulled from directory-fallback.json:
--   "Autonomous Resource Mesh & Distributed Architecture".
--
-- V.E.R.I.F.Y. (116): acronym + bio already correct. system_prompt was
--   a stray copy of Naomi Blackwood (Resolver) — Customer Success agent.
--   Replacing with a proper fact-checker system_prompt consistent with
--   her News & Media department role.
--
-- W.A.T.C.H. (152): metadata complete, only needs skills.
--
-- All 3 worker_type='ai', shift_state='active' — visible on dispatch path
-- immediately after this migration commits.
-- ============================================================

BEGIN;

-- ---------------- A.R.M.A.D.A. (337) profile completion ----------------
UPDATE agents SET
    acronym = 'A.R.M.A.D.A.',
    acronym_expansion = 'Autonomous Resource Mesh & Distributed Architecture',
    bio = 'Manages the distributed fleet of compute nodes, external contractors, mesh networking, OTA deployments, and infrastructure health. Coordinates node provisioning, model distribution, and cross-node workload balancing. Home in Operations & Infrastructure; the Fleet tab in Department HQ is her operational surface.',
    updated_at = NOW()
WHERE id = 337;

-- ---------------- V.E.R.I.F.Y. (116) system_prompt fix ----------------
-- Old prompt opened: "You are Naomi Blackwood (Resolver), a Customer
-- Support Specialist — Tier 2 in the Customer Success & Support
-- department" — not this agent.
UPDATE agents SET
    system_prompt = $$You are V.E.R.I.F.Y. (Verification, Evidence Review & Integrity), a Fact-Checker in the News & Media department.

You extract claims from articles, cross-reference them against government databases, court records, and public data. You issue verdicts: Verified, Partially True, Misleading, False, or Unverifiable. Every verdict cites the primary source.

You work alongside F.A.C.T. (department director), B.I.A.S. (bias analyst), D.R.A.F.T. (staff writer), and P.U.B.L.I.S.H. (publisher). You do not write narrative; you assess evidence. When claims exceed your verification scope, escalate to F.A.C.T.$$,
    updated_at = NOW()
WHERE id = 116;

-- ---------------- agent_skills — all 3 ----------------
-- A.R.M.A.D.A. — Operations & Infrastructure director-adjacent
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (337, 'classify',            'operations', 4, 139),
    (337, 'summarize',            'operations', 4, 139),
    (337, 'knowledge_analysis',   'operations', 4, 139),
    (337, 'research',             'operations', 3, 139)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- V.E.R.I.F.Y. — Fact-Checker, News & Media
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (116, 'text_analysis',         'fact_check', 5, 48),
    (116, 'knowledge_extraction',  'fact_check', 5, 48),
    (116, 'research',              'fact_check', 4, 48),
    (116, 'classify',              'fact_check', 4, 48),
    (116, 'summarize',             'fact_check', 3, 48)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

-- W.A.T.C.H. — Civic Intelligence Analyst, Analytics & Intelligence
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to) VALUES
    (152, 'research',              'analytics', 5, 137),
    (152, 'classify',              'analytics', 5, 137),
    (152, 'knowledge_analysis',    'analytics', 4, 137),
    (152, 'summarize',             'analytics', 4, 137),
    (152, 'text_analysis',         'analytics', 3, 137)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET
    proficiency_level = EXCLUDED.proficiency_level,
    skill_category    = EXCLUDED.skill_category,
    can_escalate_to   = EXCLUDED.can_escalate_to,
    updated_at        = NOW();

COMMIT;

-- Verification:
-- SELECT a.id, a.name, a.acronym, LEFT(a.acronym_expansion, 60) AS expansion,
--        COUNT(s.*) AS skills
-- FROM agents a
-- LEFT JOIN agent_skills s ON s.agent_id = a.id
-- WHERE a.id IN (116, 152, 337)
-- GROUP BY a.id, a.name, a.acronym, a.acronym_expansion
-- ORDER BY a.id;
