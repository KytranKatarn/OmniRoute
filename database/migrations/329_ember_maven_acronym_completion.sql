-- ============================================================
-- Fill missing acronym + acronym_expansion for E.M.B.E.R. and M.A.V.E.N.
-- Final pass for Project #261 task #1915 roster consistency audit.
--
-- Full audit of 35 active/barracked AI agents on 2026-04-19 showed
-- only these 2 with empty acronym columns. Expansions pulled from
-- each agent's own system_prompt header (authoritative — the
-- prompts were written with the canonical name already baked in).
--
-- Also normalises M.A.V.E.N.'s display_name from "Camille Dubois
-- (Maven)" to "Camille Dubois (M.A.V.E.N.)" to match the
-- R.O.S.E.T.T.A. precedent (human-name plus dotted acronym in
-- parens when both are used).
-- ============================================================

BEGIN;

-- 126 E.M.B.E.R. (Embedding & Vector Encoding Specialist)
UPDATE agents SET
    acronym = 'E.M.B.E.R.',
    acronym_expansion = 'Embedding, Memory, Bridging & Encoding Resource',
    updated_at = NOW()
WHERE id = 126;

-- 27 M.A.V.E.N. (Media Archive & Viewing Experience Navigator)
UPDATE agents SET
    acronym = 'M.A.V.E.N.',
    acronym_expansion = 'Media Archive & Viewing Experience Navigator',
    display_name = 'Camille Dubois (M.A.V.E.N.)',
    updated_at = NOW()
WHERE id = 27;

COMMIT;

-- Verification:
-- SELECT id, name, display_name, acronym, LEFT(acronym_expansion, 60) AS expansion
-- FROM agents WHERE id IN (27, 126) ORDER BY id;
