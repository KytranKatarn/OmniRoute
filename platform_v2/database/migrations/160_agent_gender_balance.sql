-- Migration 160: Agent Gender Balance + A.R.C.H.I.E. → Female
-- Project #284 — Agent Roster Integrity
-- Result: 18 female / 18 male / 3 non-binary across 39 active AI agents

BEGIN;

-- ============================================================
-- A.R.C.H.I.E. → female
-- Update gender, pronouns, portrait, avatar to reflect female COO
-- ============================================================
UPDATE agents SET
    gender = 'female',
    pronouns = 'she/her',
    portrait_prompt = 'Hyperrealistic professional headshot of a woman, ageless features suggesting wisdom beyond years, striking silver-white hair swept back with precision, sharp angular face with an almost geometric perfection, piercing eyes with a vivid teal digital iris ring, skin with an uncanny luminous clarity. High-collar LCARS command uniform in deep charcoal with gold accent trim. The apex intelligence of the platform. 8K, photorealistic.',
    avatar_generation_prompt = 'Professional portrait of a woman with ageless commanding presence, silver-white hair swept back, piercing eyes with a vivid teal digital iris ring, geometric precision to her features suggesting advanced AI processing, wearing a dark LCARS-style sci-fi command uniform with gold accent piping and the platform director emblem on the chest, calm authoritative expression, dark background with teal accent lighting, digital art style, high quality, half-body shot',
    appearance_notes = 'Ageless, silver-white hair swept back, piercing eyes with vivid teal digital iris ring, geometric precision to features, luminous skin — the platform''s apex intelligence made human'
WHERE name = 'A.R.C.H.I.E.' AND worker_type = 'ai';

-- ============================================================
-- Assign gender to 9 previously unassigned agents
-- ============================================================

-- FEMALE assignments
UPDATE agents SET gender = 'female', pronouns = 'she/her'
WHERE name = 'A.R.M.A.D.A.';  -- bio already says "her operational surface"

UPDATE agents SET gender = 'female', pronouns = 'she/her'
WHERE name = 'V.I.S.A.G.E.';  -- French: visage is feminine; facial analysis/portrait role fits

-- MALE assignments
UPDATE agents SET gender = 'male', pronouns = 'he/him'
WHERE name IN ('E.T.H.O.S.', 'H.E.R.I.T.A.G.E.', 'P.R.O.B.E.',
               'P.R.O.C.U.R.E.', 'Q.U.I.L.L.', 'R.E.S.T.O.R.E.', 'S.C.R.O.L.L.');

-- ============================================================
-- Verify final distribution
-- ============================================================
SELECT gender, COUNT(*) as count,
       STRING_AGG(name, ', ' ORDER BY name) AS agents
FROM agents
WHERE worker_type = 'ai' AND shift_state != 'decommissioned'
GROUP BY gender
ORDER BY count DESC;

COMMIT;
