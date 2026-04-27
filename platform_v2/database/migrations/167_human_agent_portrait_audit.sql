-- Migration 167: Human Agent Portrait Audit
-- Project #285 Task #2322
-- (1) Add missing avatar_generation_prompt for Crucible
-- (2) Upgrade 9 older portrait_prompts from "Professional corporate portrait photo"
--     to the new "Hyperrealistic professional headshot" standard
-- Verification: zero AI elements found in any human agent portrait — all clean

BEGIN;

-- ============================================================
-- CRUCIBLE — add missing avatar_generation_prompt
-- ============================================================
UPDATE agents SET
    portrait_prompt = 'Hyperrealistic professional headshot of a Japanese man, early 40s, precise grooming, dark hair, sharp analytical eyes, impeccably tailored bearing, wearing a smart professional blazer. Studio lighting. 8K, photorealistic.',
    avatar_generation_prompt = 'Professional portrait of a Japanese man, early 40s, precise grooming, dark hair, sharp analytical eyes, meticulous professional bearing, wearing a smart professional blazer, studio lighting, photorealistic 8K, half-body shot, no digital or sci-fi elements'
WHERE name = 'Crucible' AND worker_type = 'internal';

-- ============================================================
-- Upgrade 9 older-format portrait_prompts to Hyperrealistic standard
-- ============================================================

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of a Korean person, mid 20s, androgynous sharp features, short neat dark hair, analytical focused gaze, wearing smart professional attire. Studio lighting. 8K, photorealistic.'
WHERE name = 'Nexus' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of a Ghanaian man, mid 30s, deep brown skin, strong authoritative features, short well-groomed hair, diplomatic professional bearing, wearing a sharp business suit. Studio lighting. 8K, photorealistic.'
WHERE name = 'Envoy' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of a Russian woman, mid 30s, pale skin, light brown hair, precise analytical eyes, scholarly bearing, wearing a professional blazer. Studio lighting. 8K, photorealistic.'
WHERE name = 'Scholar' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of a Chinese-American woman, early 30s, sharp intelligent eyes, dark hair, precise engineer''s bearing, wearing a clean professional blazer. Studio lighting. 8K, photorealistic.'
WHERE name = 'CodeSmith' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of a Nigerian woman, mid 30s, warm brown skin, confident intelligent eyes, natural hair, strategic professional bearing, wearing a smart blazer. Studio lighting. 8K, photorealistic.'
WHERE name = 'Oracle' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of an Iranian woman, late 20s, warm olive skin, perceptive dark eyes, dark hair, writer''s attentive bearing, wearing a professional blazer. Studio lighting. 8K, photorealistic.'
WHERE name = 'Tempo' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of an Indian woman, mid 30s, warm brown skin, dark hair pulled back, doctor''s calm authoritative bearing, wearing a professional blazer. Studio lighting. 8K, photorealistic.'
WHERE name = 'Medic' AND worker_type = 'internal';

UPDATE agents SET portrait_prompt = 'Hyperrealistic professional headshot of a Tamil Indian woman, early 30s, warm brown skin, long dark hair, researcher''s focused attentive eyes, wearing a professional blazer. Studio lighting. 8K, photorealistic.'
WHERE name = 'Helix' AND worker_type = 'internal';

-- ============================================================
-- Verify: no AI elements, all have avatar
-- ============================================================
SELECT
    COUNT(*) FILTER (WHERE portrait_prompt ILIKE '%android%' OR portrait_prompt ILIKE '%digital iris%'
        OR portrait_prompt ILIKE '%circuit%' OR portrait_prompt ILIKE '%LCARS%') AS ai_elements_found,
    COUNT(*) FILTER (WHERE avatar_generation_prompt IS NULL OR avatar_generation_prompt = '') AS missing_avatar,
    COUNT(*) FILTER (WHERE portrait_prompt LIKE 'Hyperrealistic%') AS hyperrealistic_format,
    COUNT(*) AS total
FROM agents WHERE worker_type = 'internal' AND shift_state = 'active';

COMMIT;
