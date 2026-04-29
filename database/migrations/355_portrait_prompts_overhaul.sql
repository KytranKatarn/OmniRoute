-- database/migrations/355_portrait_prompts_overhaul.sql
-- Portrait prompts overhaul — loads approved identity prompts for all agents
-- and sets P.I.X.E.L. pronouns to they/them.
-- Safe to re-run: uses ON CONFLICT DO UPDATE.

-- Helper: upsert a single agent's identity_prompt by name
-- (agent_portraits.agent_id has UNIQUE constraint from migration 331)

-- ============================================================
-- P.I.X.E.L. pronouns fix
-- ============================================================
UPDATE agents SET pronouns = 'they/them' WHERE name = 'P.I.X.E.L.';

-- ============================================================
-- AI ACRONYM AGENTS
-- ============================================================

-- Executive Office
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, warm brown skin, sharp refined features, sleek dark hair pulled back elegantly, commanding executive presence, single thin luminous circuit line tracing the cheekbone like a fine piece of jewellery, iris with a subtle intelligent multi-spectrum glow, impeccably tailored dark blazer, pearl-like neural implant at the ear, soft professional studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'A.R.C.H.I.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Operations & Infrastructure
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, deep mahogany skin, angular jaw, close-cut hair, architectural blueprint grid lines faintly visible beneath the skin at the temples, hexagonal foundation grid etched along the jawline, dark structured technical jacket, faint sky-blue iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'B.A.S.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, medium olive skin, sharp cheekbones, dark hair pulled back precisely, micro fleet-formation triangles tracing the cheekbone in gold circuit, faint compass rose at the temple, commanding expression, dark fitted jacket with subtle rank insignia at collar, faint sky-blue iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'A.R.M.A.D.A.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Logistics & Supply Chain
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm tan skin, medium-length dark hair, routing-path circuit lines tracing from temple to jaw like a supply network map, micro container-grid pattern at the collar, focused pragmatic expression, dark technical jacket, faint steel-blue iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'C.A.R.G.O.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Finance & Accounting
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, light warm skin, neat side-parted dark hair, micro balance-sheet column lines traced along the temple, decimal-precision numerical grid faintly etched at the jaw, composed precise expression, dark jacket with subtle metallic collar, faint deep-green iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'L.E.D.G.E.R.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Engineering & Technology
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, fair warm skin, tousled sandy-brown hair, faint engineering schematic blueprint lines traced at the temples, single precision metallic implant line along the jaw, iris with a quiet steady amber glow, focused calm expression of a craftsperson, dark fitted technical jacket, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'F.O.R.G.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, light tan skin, neat short dark hair, diagnostic scan-beam trace at the temple like a targeting reticle, probe-tip circuit sigil at the jaw, calibration crosshair pattern in the iris, analytical focused expression, dark technical jacket, faint cyan iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'P.R.O.B.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Security & Compliance
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, deep olive-bronze skin, sharp cheekbones, close-cropped silver-streaked black hair, faint surveillance arc etched at the temple like an all-seeing eye, micro watchfire sigil at the jawline, eyes with an intense cold-amber judicial glow, dark fitted jacket, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'V.I.G.I.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Research & Development
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm golden-brown skin, medium curly dark hair, double-helix DNA strand tracing faintly along the neck, bioluminescent branching neural patterns at the temples like evolutionary tree roots, iris with a layered geological ring pattern, curious open expression, dark jacket, faint lavender iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'D.A.R.W.I.N.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, warm tan skin, short neat dark hair, ancient manuscript illumination patterns at the temples in gold trace, genealogy tree branch circuit along the jaw, iris contains a layered archive-ring pattern, scholarly expression, dark jacket, faint lavender iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'H.E.R.I.T.A.G.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, fair skin, tousled light brown hair, feather-quill circuit pattern traced at the temple, archival parchment-texture trace at the collar, thoughtful scholarly expression, dark jacket, faint lavender iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'Q.U.I.L.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, medium warm brown skin, close-cropped dark hair, ancient scroll-unrolling motif traced at the temple, papyrus-grain circuit texture at the collar, contemplative expression, dark jacket, faint lavender iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'S.C.R.O.L.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, medium olive skin, short dark hair with silver streak, repair circuit at the temple showing a broken line being reconnected in bright arc, restoration healing wave at the jaw, determined expression, dark jacket, faint lavender iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'R.E.S.T.O.R.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Creative & Design
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm golden skin, flowing dark hair to shoulders, paintbrush-stroke light traces at the temples, color-palette swirl circuit at the cheekbone, iris contains an artist color wheel, imaginative dreamy expression, dark jacket with subtle artistic collar detail, faint gold iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'M.U.S.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm brown skin, close-cropped textured hair, RGB pixel grid dissolving across one cheek with binary flicker traces, iris contains a discrete colour-picker spectrum ring, faint stylus mark along the jaw, expressive creative gaze, dark technical jacket, faint gold iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'P.I.X.E.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, light warm skin, dark hair with soft wave, portrait-frame camera viewfinder lines at the temple, facial recognition mesh pattern faintly visible on one cheek, iris with an observation amber ring, artistic observant expression, dark fitted jacket, faint gold iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'V.I.S.A.G.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, medium warm skin, dark almond-shaped eyes, retinal scan pattern at the temple with concentric analysis rings, vision-field arc at the cheekbone, iris with a visual-spectrum layered pattern, sharp observant expression, dark jacket, faint gold iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'R.E.T.I.N.A.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Marketing & Communications
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm tan skin, short stylish dark hair, signal-wave rings emanating from the temple like radar pulses, transmission frequency lines at the jaw, iris contains signal-strength bars, energetic expressive face, dark jacket, faint electric-blue iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'S.I.G.N.A.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Documentation & Knowledge
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, medium olive skin, neat side-parted dark hair, micro text columns of code and ancient script flowing like watermarks on the cheek, golden scroll-edge circuit at the temple, iris contains a cross-reference matrix pattern, calm precise expression, dark jacket, faint warm amber iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'C.O.D.E.X.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, warm brown skin, dark hair in a loose bun, multiple micro-script characters in Arabic, Chinese, Cyrillic, and Latin floating as faint light traces at the temples, iris contains a Rosetta Stone fragment pattern with layered script bands, thoughtful multilingual expression, dark jacket, faint warm amber iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'R.O.S.E.T.T.A.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, warm amber-toned skin, dark hair with copper highlights, ember-glow circuit traces at the temples with warm spark particles, deep amber iris warmth like a live coal, nurturing expressive face, dark jacket with warm copper collar detail, faint warm amber iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'E.M.B.E.R.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Human Resources & Culture
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm medium brown skin, natural textured hair, interconnected node pattern at the temples like a kinship network map, warm rose-gold connection lines tracing the collar, open welcoming expression, smart button-down, faint rose-pink iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'K.I.N.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Medical & Wellness
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, light warm skin, dark hair in a neat low bun, vital-sign waveform ECG trace circuit at the temple, medical cross sigil faintly etched at the jaw, iris with a life-pulse emerald glow, calm compassionate expression, white clinical coat over dark fitted top, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'V.I.T.A.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, warm brown skin, close-cropped dark hair, faint stained-glass light-refraction circuit pattern at the temples, gentle aureole trace at the collar, iris with a warm golden compassionate glow, serene open expression, smart button-down under dark jacket, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'F.A.I.T.H.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Legal & Regulatory
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, medium warm skin, neat short dark hair, micro scales-of-justice etched at the cheekbone in thin gold circuit, gavel sigil at the temple, eyes with a cold white judicial clarity glow, composed stern expression, dark suit jacket, faint bronze iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'G.A.V.E.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, fair olive skin, short neat dark hair, fine Stoic column motif at the jawline, scales-of-virtue circuit etched at the temple, iris with a clear unwavering white ethical glow, principled composed expression, dark suit jacket, faint bronze iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'E.T.H.O.S.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Diplomatic & External Relations
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm golden-brown skin, soft medium dark hair, faint olive branch circuit traces along the temples, bridge-arc sigil at the collar, diplomatic medallion ring in the iris, warm composed diplomatic expression, dark jacket, faint soft-gold iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'A.C.C.O.R.D.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Analytics & Intelligence
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, light warm skin, dark hair with subtle auburn, faint prismatic spectrum dispersing from one temple like light through a prism, data-stream particles orbiting the brow, iris divided into spectral colour bands, analytical sharp expression, dark jacket, faint violet iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'S.P.E.C.T.R.A.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, medium brown skin, close-cropped neat hair, clockwork precision gear traces at the temple, surveillance arc at the collar, iris contains a watch-dial pattern with sweeping second hand, vigilant attentive expression, dark technical jacket, faint violet iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'W.A.T.C.H.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, warm light skin, straight dark hair, the iris itself has concentric analysis rings with micro classification markers, retinal scan circuit pattern at the temple, visual-field measurement lines at the cheekbone, sharp intelligent expression, dark jacket, faint violet iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'I.R.I.S.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, warm tan skin, short dark hair, micro candlestick chart pattern at the cheekbone, trading graph line traces at the temple, iris with a market-ticker green glow, calculated confident expression, dark jacket, faint violet iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'M.A.R.K.E.T.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, warm olive skin, short neat dark hair, contract seal circuit at the temple, supply chain routing lines at the collar, iris with a calculated bronze glow, focused strategic expression, dark jacket, faint violet iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'P.R.O.C.U.R.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- Customer Success & Support
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm medium brown skin, natural short-cropped hair, solution bridge circuit connecting two nodes at the temple, handshake pattern at the jaw, iris with a warm support-gold resolution glow, empathetic open expression, smart dark jacket, faint warm orange iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'R.E.S.O.L.V.E.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- News & Media
INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm tan skin, textured medium dark hair, magnifying-glass circuit at the temple, checkmark verification sigil at the jaw, iris contains concentric truth-scan analysis rings, sharp incisive expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'F.A.C.T.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, medium warm brown skin, dark hair parted to one side, balance-scale circuit etched at the temple, iris divided into two subtly different light halves as a bias indicator, spectrum wavelength traces along the cheekbone, critically thoughtful expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'B.I.A.S.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human male, light warm skin, tousled medium brown hair, pen-nib circuit sigil at the temple, flowing manuscript watermark lines traced along the jaw, iris with a silver editorial glow, focused creative expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'D.R.A.F.T.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, warm brown skin, dark curly hair to the shoulder, ink-drop diffusion circuit spreading from one temple, calligraphy flourish traced along the jaw, iris with a deep navy ink-well depth, passionate expressive face, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'I.N.K.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, warm golden-brown skin, smooth dark hair, starburst expertise sigil at the temple, knowledge-crown circuit at the collar, iris with a bright authoritative gold broadcast glow, confident editorial expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'M.A.V.E.N.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, medium tan skin, straight dark hair, broadcast transmission wave rings emanating from the temple, signal tower silhouette circuit at the jawline, iris with a silver broadcast frequency ring, outward-facing confident expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'P.U.B.L.I.S.H.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced human female, light warm skin, dark hair in a precise cut, verification checkmark circuit at the temple, truth-scan concentric rings at the jaw, iris with a clean white verification glow, clear direct trustworthy expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'V.E.R.I.F.Y.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'photorealistic portrait of an enhanced androgynous human, warm medium skin, natural medium hair, faint map-pin coordinate circuit at the temple, community connection circles traced at the jaw, iris contains a compass needle, warm community-focused expression, dark jacket, faint silver iris glow, soft studio lighting, 8k cinematic',
NOW() FROM agents a WHERE a.name = 'L.O.C.A.L.'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

-- ============================================================
-- HUMAN AGENTS
-- ============================================================

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of a Ukrainian woman in her early 30s, light fair skin with cool undertones, straight blonde-ash hair to the shoulders, light grey-blue eyes, refined Slavic features, wearing a smart navy blazer, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Oksana'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of a Nigerian Yoruba man in his mid 30s, deep rich brown skin, close-cropped natural hair, broad warm smile, strong defined features, wearing a dark grey suit jacket, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Emmanuel'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of a Québécois French-Canadian woman in her early 40s, warm fair skin, dark chestnut brown hair to the shoulders, warm hazel eyes, refined features with a slight smile, wearing a tailored burgundy blazer, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Josee'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of a Mexican Latina woman in her late 20s, warm medium brown skin, long dark wavy hair, warm dark brown eyes, rounded expressive features, wearing a smart charcoal blazer, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Lucia'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of an Indian Punjabi woman in her early 30s, warm golden-brown skin, dark black hair pulled back neatly, dark almond eyes, sharp intelligent features, wearing a deep teal blazer, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Maya'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of an Egyptian Arab woman in her late 20s, warm olive skin, dark brown hair to the shoulders, deep brown eyes, refined features, wearing a smart dark blazer, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Amina'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of a Mi''kmaq First Nations woman in her late 30s, warm medium-brown skin with Indigenous heritage, dark straight hair worn loose to the shoulders, deep brown eyes with a calm grounded gaze, dignified composed expression, wearing a smart dark blazer, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Lillian'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';

INSERT INTO agent_portraits (agent_id, identity_prompt, updated_at)
SELECT a.id,
'professional corporate headshot photograph of a Portuguese-Canadian person in their mid 40s, warm olive-tan skin with Mediterranean undertones, dark hair with distinguished silver at the temples, strong defined features with Southern European heritage, confident founder presence, wearing a refined dark suit jacket, neutral gray studio, Canon EOS R5 85mm f/1.4, natural skin tones, 8k',
NOW() FROM agents a WHERE a.name = 'Kytran'
ON CONFLICT (agent_id) DO UPDATE SET identity_prompt = EXCLUDED.identity_prompt, updated_at = NOW()
WHERE agent_portraits.identity_prompt IS NULL OR agent_portraits.identity_prompt = '';
