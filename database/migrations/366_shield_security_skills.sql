-- Migration 366: Add canonical security skills to S.H.I.E.L.D.
-- 2026-05-01 — idle-agent routing fix
--
-- S.H.I.E.L.D.'s only non-gh skill was "security-review" (hyphen) which
-- never matched the dispatcher capability strings "security" or
-- "vulnerability_scan". This migration adds the canonical skill names so
-- S.H.I.E.L.D. is reachable via normal dispatch alongside V.I.G.I.L.
-- CAPABILITY_DEPARTMENT_MAP was also updated to map "security-review" →
-- Security & Compliance (PR fix/idle-agents-routing-gap).

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level)
SELECT a.id, v.skill_name, v.lvl
FROM agents a
CROSS JOIN (VALUES
    ('security',         5),
    ('security_review',  5),
    ('vulnerability_scan', 4)
) AS v(skill_name, lvl)
WHERE a.name = 'S.H.I.E.L.D.'
ON CONFLICT (agent_id, skill_name) DO NOTHING;
