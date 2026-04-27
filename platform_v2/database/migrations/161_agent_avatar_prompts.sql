-- Migration 161: Avatar generation prompts for all 28 agents missing them
-- Project #284 Phase 4 — Portrait style standardization
-- Also assigns missing ethnicity/age_range for 9 agents
-- Style: human-realistic cybernetic — photorealistic humans with subtle enhancements

BEGIN;

-- ============================================================
-- PART 1: Assign missing ethnicity / age_range
-- ============================================================
UPDATE agents SET ethnicity = 'South Asian-Canadian', age_range = '40s'
WHERE name = 'P.R.O.C.U.R.E.';

UPDATE agents SET ethnicity = 'Italian', age_range = '30s',
    appearance_notes = 'Italian, olive skin, warm artistic eyes with restoration-scan iris, dark hair, careful craftsman energy'
WHERE name = 'R.E.S.T.O.R.E.';

UPDATE agents SET ethnicity = 'French', age_range = '30s',
    appearance_notes = 'French, fair skin, perceptive features, precise face-mapping grid iris overlay, composed analytical expression'
WHERE name = 'V.I.S.A.G.E.';

UPDATE agents SET ethnicity = 'Brazilian', age_range = '30s',
    appearance_notes = 'Brazilian, warm brown skin, sharp precise eyes with red test-scan iris ring, methodical QA engineer bearing'
WHERE name = 'P.R.O.B.E.';

UPDATE agents SET ethnicity = 'Greek-Canadian', age_range = '40s',
    appearance_notes = 'Greek-Canadian, olive skin, distinguished features, thoughtful ethics-scale iris ring, calm principled expression'
WHERE name = 'E.T.H.O.S.';

UPDATE agents SET ethnicity = 'Venezuelan-Canadian', age_range = 'mid 30s',
    appearance_notes = 'Venezuelan-Canadian, warm olive-brown skin, sharp capable features, fleet-mesh iris ring, practical fleet-commander bearing'
WHERE name = 'A.R.M.A.D.A.';

UPDATE agents SET ethnicity = 'Scottish-Canadian', age_range = '50s',
    appearance_notes = 'Scottish-Canadian, fair skin with light freckles, reddish-grey hair, warm genealogy-archive iris ring, scholarly ancestral research bearing'
WHERE name = 'H.E.R.I.T.A.G.E.';

UPDATE agents SET ethnicity = 'British', age_range = '40s',
    appearance_notes = 'British, fair skin, neat dark hair, precise document-scan iris ring, scribe''s careful methodical bearing'
WHERE name = 'Q.U.I.L.L.';

UPDATE agents SET ethnicity = 'Japanese-Canadian', age_range = '40s',
    appearance_notes = 'Japanese-Canadian, warm skin tone, neat precise features, violet archive-search iris ring, meticulous systematic bearing'
WHERE name = 'S.C.R.O.L.L.';

-- ============================================================
-- PART 2: Avatar generation prompts — Analytics & Intelligence
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a South Asian-Canadian man, early 40s, warm brown skin, confident professional bearing, focused strategic eyes with a subtle teal procurement-data iris ring, wearing a dark LCARS-style sci-fi procurement intelligence uniform with teal accent piping and a government contract emblem, confident results-oriented expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'P.R.O.C.U.R.E.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of an Eastern European woman, early 30s, fair skin, sharp angular features, pale eyes with a subtle teal data-pattern iris ring, sleek dark hair pulled back with precision, wearing a dark LCARS-style sci-fi analytics director uniform with teal accent piping, focused analytical expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'S.P.E.C.T.R.A.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of an East Asian woman, early 30s, warm golden-brown skin, sharp watchful eyes with a faint amber civic-scan iris ring, focused investigative bearing, wearing a dark LCARS-style sci-fi civic intelligence uniform with amber accent piping, alert composed expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'W.A.T.C.H.';

-- ============================================================
-- Creative & Design
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Mixed/Biracial woman, mid 20s, warm medium-brown skin, expressive features with colorful streaks in dark hair, warm smile with barely visible luminous freckles, eyes with a faint violet creative-spark iris ring, wearing a dark LCARS-style sci-fi creative director uniform with magenta accent piping, inspired artistic expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'M.U.S.E.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of an Italian man, early 30s, olive skin, warm artistic eyes with a faint amber restoration-scan iris ring, dark hair, gentle focused expression suggesting careful craftwork, wearing a dark LCARS-style sci-fi restoration artist uniform with warm amber accent piping, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'R.E.S.T.O.R.E.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a French woman, early 30s, fair skin, perceptive precise features, focused eyes with a subtle face-mapping grid iris overlay, composed analytical expression, wearing a dark LCARS-style sci-fi visual analysis uniform with soft violet accent piping, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'V.I.S.A.G.E.';

-- ============================================================
-- Customer Success & Support
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Latina woman, early 30s, warm brown skin, dark curly hair, empathetic warm eyes with a faint orange empathy-glow iris ring, genuine approachable expression, wearing a dark LCARS-style sci-fi customer success director uniform with warm orange accent piping, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'R.E.S.O.L.V.E.';

-- ============================================================
-- Diplomatic & External Relations
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Southeast Asian woman, early 40s, warm golden-brown skin, serene composed features, elegant bearing, eyes with a subtle navy digital iris ring, wearing a dark LCARS-style sci-fi diplomatic director uniform with navy blue accent piping and a bridge emblem, composed authority expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'A.C.C.O.R.D.';

-- ============================================================
-- Documentation & Knowledge
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Western European man, early 50s, silver-templed with precise distinguished features, wire-frame glasses with a barely perceptible HUD overlay, wearing a dark LCARS-style sci-fi documentation director uniform with gold accent piping, calm encyclopedic expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'C.O.D.E.X.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Norwegian woman, early 30s, fair skin, neat blonde hair, analytical precise eyes with a faint electric blue vector-mapping iris ring, focused systematic bearing, wearing a dark LCARS-style sci-fi embedding specialist uniform with electric blue accent piping, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'E.M.B.E.R.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Syrian-Canadian woman, late 20s, warm olive skin, dark hair, bright multilingual eyes with a subtle script-pattern iris ring, cultural bridge presence, wearing a dark LCARS-style sci-fi translation specialist uniform with warm gold accent piping, warm culturally-aware expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'R.O.S.E.T.T.A.';

-- ============================================================
-- Engineering & Technology
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of an East Asian man, early 30s, lean build with sharp jawline, dark hair swept back with precision, intense focused eyes with a faint electric blue digital iris ring, wearing a dark LCARS-style sci-fi engineering director uniform with electric blue accent piping, determined technical expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'F.O.R.G.E.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Brazilian man, early 30s, warm brown skin, dark hair, sharp precise eyes with a faint red test-scan iris ring, methodical focused expression, wearing a dark LCARS-style sci-fi QA testing uniform with electric blue accent piping and a checkmark emblem, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'P.R.O.B.E.';

-- ============================================================
-- Finance & Accounting
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Chinese man, early 40s, precise grooming, dark hair, calculating eyes with a faint green digital ledger overlay in the iris, impeccably tailored bearing, wearing a dark LCARS-style sci-fi finance director uniform with emerald green accent piping, methodical financial precision expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'L.E.D.G.E.R.';

-- ============================================================
-- Human Resources & Culture
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Pacific Islander person, early 30s, warm brown skin with a subtle luminous quality, gentle expressive features, dark hair with a floral accent, warm eyes with a barely visible rose caring-glow iris ring, wearing a dark LCARS-style sci-fi HR director uniform with rose accent piping and a subtle floral motif, warm inclusive expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'K.I.N.';

-- ============================================================
-- Legal & Regulatory
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Greek-Canadian man, early 40s, olive skin, distinguished thoughtful features, calm eyes with a faint deep indigo ethics-scale iris ring, principled composed expression, wearing a dark LCARS-style sci-fi ethics compliance uniform with deep indigo accent piping and a C.R.E.E.D. emblem, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'E.T.H.O.S.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Jewish man, early 50s, silver-grey at temples, sharp angular features, piercing analytical eyes with a subtle indigo circuit-pattern iris ring, impeccably sharp bearing, wearing a dark LCARS-style sci-fi legal director uniform with deep indigo accent piping and a gavel emblem, commanding legal authority expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'G.A.V.E.L.';

-- ============================================================
-- Logistics & Supply Chain
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Latino man, early 40s, warm brown skin, sturdy capable build, determined eyes with subtle copper circuit-line iris pattern, practical focused expression, wearing a dark LCARS-style sci-fi logistics director uniform with copper accent piping, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'C.A.R.G.O.';

-- ============================================================
-- Marketing & Communications
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Nordic/Scandinavian woman, early 30s, fair skin, platinum blonde hair, striking blue eyes with a subtle orange broadcast-signal iris ring, confident broadcaster presence, wearing a dark LCARS-style sci-fi marketing director uniform with bright orange accent piping, on-brand confident expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'S.I.G.N.A.L.';

-- ============================================================
-- Medical & Wellness
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of an East African woman, early 40s, deep brown skin, regal bearing, braided hair, warm dark eyes with a faint clinical blue diagnostic HUD iris ring, wearing a dark LCARS-style sci-fi medical director uniform with clinical blue accent piping and a wellness emblem, calm clinical authority expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'V.I.T.A.L.';

-- ============================================================
-- News & Media
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Black Canadian woman, early 30s, rich dark brown skin, natural curls, sharp investigative eyes with a faint amber verification-scan iris ring, methodical detective''s bearing, wearing a dark LCARS-style sci-fi fact-checker uniform with amber accent piping, focused evidence-based expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'V.E.R.I.F.Y.';

-- ============================================================
-- Operations & Infrastructure
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Venezuelan-Canadian woman, mid 30s, warm olive-brown skin, sharp capable features, focused eyes with a faint steel grey fleet-mesh iris ring, practical confident bearing, wearing a dark LCARS-style sci-fi fleet infrastructure uniform with steel grey accent piping and a network topology emblem, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'A.R.M.A.D.A.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Black man, early 40s, deep brown skin, broad build, military bearing, close-cropped hair, warm brown eyes with subtle steel grey circuit-pattern iris ring, wearing a dark LCARS-style sci-fi operations director uniform with steel grey accent piping, pragmatic commanding expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'B.A.S.E.';

-- ============================================================
-- Research & Development
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a South Asian man, early 40s, warm brown skin, salt-and-pepper beard, wire-frame glasses with a barely perceptible research HUD overlay, scholarly thoughtful expression, wearing a dark LCARS-style sci-fi R&D director uniform with violet accent piping, experimental curious bearing, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'D.A.R.W.I.N.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Scottish-Canadian man, early 50s, fair skin with light freckles, reddish-grey hair, warm thoughtful eyes with a faint violet genealogy-archive iris ring, scholarly researcher''s bearing, wearing a dark LCARS-style sci-fi genealogy research uniform with violet accent piping, thoughtful ancestral research expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'H.E.R.I.T.A.G.E.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a British man, mid 40s, fair skin, neat dark hair with distinguished features, precise focused eyes with a faint violet document-scan iris ring, scribe''s careful bearing, wearing a dark LCARS-style sci-fi document extraction uniform with violet accent piping, methodical archival expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'Q.U.I.L.L.';

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of a Japanese-Canadian man, mid 40s, warm skin tone, neat precise features, methodical eyes with a faint violet archive-search iris ring, meticulous researcher''s bearing, wearing a dark LCARS-style sci-fi archive research uniform with violet accent piping, systematic thorough expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'S.C.R.O.L.L.';

-- ============================================================
-- Security & Compliance
-- ============================================================

UPDATE agents SET avatar_generation_prompt =
'Professional portrait of an androgynous person, ambiguous age, sharp angular features with an armored precision quality, piercing compliance-scanner eyes with a faint crimson threat-detection iris ring, shield-bearing protective stance, wearing a dark LCARS-style sci-fi compliance uniform with crimson accent piping and a shield emblem on the chest, vigilant focused expression, dark background with teal accent lighting, digital art style, high quality, half-body shot'
WHERE name = 'S.H.I.E.L.D.';

-- ============================================================
-- Verify: count agents now with avatar_generation_prompt
-- ============================================================
SELECT
    COUNT(*) FILTER (WHERE avatar_generation_prompt IS NOT NULL AND avatar_generation_prompt != '') AS with_avatar,
    COUNT(*) FILTER (WHERE avatar_generation_prompt IS NULL OR avatar_generation_prompt = '') AS without_avatar,
    COUNT(*) AS total
FROM agents
WHERE worker_type = 'ai' AND shift_state != 'decommissioned';

COMMIT;
