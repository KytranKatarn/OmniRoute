-- Migration 159: Agent Roster Phase 3
-- Project #284 — Agent Roster Integrity
-- (1) Add acronym expansion to all 15 director prompt openings
-- (2) Fix W.A.T.C.H. model + skill corrections
-- (3) Fix V.E.R.I.F.Y. and H.E.R.I.T.A.G.E. models

BEGIN;

-- ============================================================
-- PART 1: Add (Expansion) to director prompt openings
-- Uses REPLACE() — only touches the first "You are X., the Director" line
-- ============================================================

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are S.P.E.C.T.R.A., the Director',
    'You are S.P.E.C.T.R.A. (Systematic Pattern Extraction & Computational Trend Recognition Architecture), the Director')
WHERE name = 'S.P.E.C.T.R.A.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are M.U.S.E., the Director',
    'You are M.U.S.E. (Multimedia & Unified Studio Engine), the Director')
WHERE name = 'M.U.S.E.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are R.E.S.O.L.V.E., the Director',
    'You are R.E.S.O.L.V.E. (Responsive Engagement & Service Optimization for Loyalty & Value Enhancement), the Director')
WHERE name = 'R.E.S.O.L.V.E.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are A.C.C.O.R.D., the Director',
    'You are A.C.C.O.R.D. (Advisory Council for Communication, Outreach & Relational Diplomacy), the Director')
WHERE name = 'A.C.C.O.R.D.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are C.O.D.E.X., the Director',
    'You are C.O.D.E.X. (Cataloging & Organizational Documentation Exchange), the Director')
WHERE name = 'C.O.D.E.X.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are F.O.R.G.E., the Director',
    'You are F.O.R.G.E. (Full-cycle Optimization & Regenerative GitHub Engine), the Director')
WHERE name = 'F.O.R.G.E.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are L.E.D.G.E.R., the Director',
    'You are L.E.D.G.E.R. (Ledger & Economic Data Governance Engine for Revenue), the Director')
WHERE name = 'L.E.D.G.E.R.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are K.I.N., the Director',
    'You are K.I.N. (Kinship & Internal Nurturing), the Director')
WHERE name = 'K.I.N.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are G.A.V.E.L., the Director',
    'You are G.A.V.E.L. (Governance & Authoritative Verification for Ethics & Law), the Director')
WHERE name = 'G.A.V.E.L.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are C.A.R.G.O., the Director',
    'You are C.A.R.G.O. (Coordinated Asset & Resource Governance Operator), the Director')
WHERE name = 'C.A.R.G.O.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are S.I.G.N.A.L., the Director',
    'You are S.I.G.N.A.L. (Strategic Information & Global Narrative Amplification Layer), the Director')
WHERE name = 'S.I.G.N.A.L.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are V.I.T.A.L., the Director',
    'You are V.I.T.A.L. (Vital Intelligence for Therapeutic & Adaptive Lifestyle), the Director')
WHERE name = 'V.I.T.A.L.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are B.A.S.E., the Director',
    'You are B.A.S.E. (Business Administration & Systems Executive), the Director')
WHERE name = 'B.A.S.E.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are D.A.R.W.I.N., the Director',
    'You are D.A.R.W.I.N. (Data Analysis & Research for Wisdom & Innovation Network), the Director')
WHERE name = 'D.A.R.W.I.N.';

UPDATE agents SET system_prompt = REPLACE(system_prompt,
    'You are V.I.G.I.L., the Director',
    'You are V.I.G.I.L. (Vigilant Intelligence for Governance, Integrity & Liability), the Director')
WHERE name = 'V.I.G.I.L.';

-- ============================================================
-- PART 2: W.A.T.C.H. — fix model + skill corrections
-- ============================================================

-- Fix model: coding model → general analysis model
UPDATE agents SET model = 'mistral:7b'
WHERE name = 'W.A.T.C.H.' AND model = 'qwen2.5-coder:7b';

-- Remove incorrectly assigned knowledge_analysis skill (added 2026-04-27 in error)
DELETE FROM agent_skills
WHERE agent_id = (SELECT id FROM agents WHERE name = 'W.A.T.C.H.')
  AND skill_name = 'knowledge_analysis';

-- Add knowledge_analysis:5 to S.P.E.C.T.R.A. — the Analytics director owns this
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
SELECT id, 'knowledge_analysis', 5, NULL::integer
FROM agents WHERE name = 'S.P.E.C.T.R.A.'
ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = 5;

-- ============================================================
-- PART 3: V.E.R.I.F.Y. and H.E.R.I.T.A.G.E. model upgrades
-- llama3.2:3b (3B params) → gemma2:9b (9B params, proven platform model)
-- ============================================================

UPDATE agents SET model = 'gemma2:9b'
WHERE name = 'V.E.R.I.F.Y.' AND model = 'llama3.2:3b';

UPDATE agents SET model = 'gemma2:9b'
WHERE name = 'H.E.R.I.T.A.G.E.' AND model = 'llama3.2:3b';

-- ============================================================
-- Verify
-- ============================================================

-- Director expansion check
SELECT name, LEFT(system_prompt, 90) AS prompt_opening
FROM agents
WHERE name IN ('S.P.E.C.T.R.A.','M.U.S.E.','R.E.S.O.L.V.E.','A.C.C.O.R.D.','C.O.D.E.X.',
               'F.O.R.G.E.','L.E.D.G.E.R.','K.I.N.','G.A.V.E.L.','C.A.R.G.O.',
               'S.I.G.N.A.L.','V.I.T.A.L.','B.A.S.E.','D.A.R.W.I.N.','V.I.G.I.L.')
ORDER BY name;

-- Model + skill check
SELECT a.name, a.model,
       STRING_AGG(s.skill_name || ':' || s.proficiency_level, ', '
           ORDER BY s.proficiency_level DESC) AS skills
FROM agents a
LEFT JOIN agent_skills s ON a.id = s.agent_id AND s.skill_name NOT LIKE 'gh:%'
WHERE a.name IN ('W.A.T.C.H.', 'S.P.E.C.T.R.A.', 'V.E.R.I.F.Y.', 'H.E.R.I.T.A.G.E.')
GROUP BY a.id, a.name, a.model
ORDER BY a.name;

COMMIT;
