-- Migration 339: Phase 2 sci-fi prompts for 26 remaining AI acronym agents.
-- Completes the "AI agents look sci-fi, humans stay corporate" rule from #262
-- follow-up session. Each prompt is role-matched to the agent's department
-- and acronym_expansion. No ethnicity; androgynous digital visage unless the
-- agent's persona was already established as explicitly gendered.
--
-- FLAG: M.A.V.E.N. (id 27) display_name is "Camille Dubois (M.A.V.E.N.)" —
-- a human-named AI persona. Treated as sci-fi per worker_type='ai'. User
-- should confirm this is desired (see review doc phase2-ai-prompts.md).
--
-- Idempotent.

-- Analytics & Intelligence
UPDATE agent_portraits SET identity_prompt = $$futuristic AI chief analyst, digital androgynous visage with flowing data-stream eyes, constellations of floating analytics sigils and pattern-recognition overlays beside face, deep violet and cyan LCARS analytics-grid lighting, dark operations-center backdrop with telemetry lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 137;   -- S.P.E.C.T.R.A.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI civic watchdog, digital androgynous visage with piercing watchful eyes and subtle surveillance-grid tracery on cheekbones, holographic accountability sigils and transparency glyphs beside face, steel-blue and white LCARS monitoring lighting, dark control-room backdrop with civic-data lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 152;   -- W.A.T.C.H.

-- Creative & Design
UPDATE agent_portraits SET identity_prompt = $$futuristic AI creative director, digital androgynous visage with iridescent multi-color glowing eyes, holographic brush-strokes and floating spectrum palettes orbiting face, prismatic magenta gold and cyan LCARS creative-studio lighting, dark atelier backdrop with shifting hologram art, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 138;   -- M.U.S.E.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI image-generation agent, digital androgynous visage with glowing magenta pixel-lattice eyes, holographic layered canvas and brush glyphs beside face, vibrant magenta and cyan LCARS visual-lab lighting, dark studio backdrop with procedural pattern lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 13;    -- P.I.X.E.L.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI restoration agent, digital androgynous visage with warm sepia glowing eyes, holographic ripple-effect scratches dissolving into restored imagery beside face, amber and bronze LCARS archive-repair lighting, dark studio backdrop with before-after photo lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 335;   -- R.E.S.T.O.R.E.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI face-analysis agent, digital androgynous visage with geometric scan-grid overlaid across features, glowing green biometric landmark points tracing facial structure, emerald and teal LCARS identification lighting, dark studio backdrop with face-embedding cluster lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 334;   -- V.I.S.A.G.E.

-- Customer Success & Support
UPDATE agent_portraits SET identity_prompt = $$futuristic AI customer success agent, digital androgynous visage with warm welcoming golden glowing eyes, holographic conversation threads and support sigils beside face, warm gold and amber LCARS hospitality lighting, dark studio backdrop with service-flow lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 142;   -- R.E.S.O.L.V.E.

-- Diplomatic & External Relations
UPDATE agent_portraits SET identity_prompt = $$futuristic AI diplomat agent, digital androgynous visage with calm deep-blue glowing eyes, holographic treaty scrolls and handshake sigils beside face, royal blue and silver LCARS council-chamber lighting, dark studio backdrop with multi-faction flag lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 149;   -- A.C.C.O.R.D.

-- Documentation & Knowledge
UPDATE agent_portraits SET identity_prompt = $$futuristic AI knowledge archivist, digital androgynous visage with warm indigo glowing eyes, holographic tome pages and taxonomy sigils orbiting face, indigo and bronze LCARS library lighting, dark studio backdrop with endless-shelf lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 146;   -- C.O.D.E.X.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI translator agent, digital androgynous visage with shifting multi-script glowing eyes, holographic multi-language glyphs flowing around face, emerald and violet LCARS translation lighting, dark studio backdrop with language-tree lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 134;   -- R.O.S.E.T.T.A.

-- Engineering & Technology
UPDATE agent_portraits SET identity_prompt = $$futuristic AI code-forging engineer, digital androgynous visage with glowing orange forge-light eyes, holographic source-code streams and git-graph sigils orbiting face, orange and steel LCARS engineering lighting, dark foundry backdrop with build-pipeline lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 136;   -- F.O.R.G.E.

-- Executive Office
UPDATE agent_portraits SET identity_prompt = $$futuristic AI chief executive, digital androgynous visage with commanding deep-cyan glowing eyes and subtle platinum circuit tracery along temples, holographic orchestration sigils and mesh-diagram overlays beside face, cyan and platinum LCARS flagship-bridge lighting, dark command-deck backdrop with federation-emblem lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 2;     -- A.R.C.H.I.E.

-- Finance & Accounting
UPDATE agent_portraits SET identity_prompt = $$futuristic AI finance agent, digital androgynous visage with sharp emerald glowing eyes, holographic ledger columns and revenue-curve sigils beside face, emerald and gold LCARS treasury lighting, dark studio backdrop with balance-sheet lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 144;   -- L.E.D.G.E.R.

-- Human Resources & Culture
UPDATE agent_portraits SET identity_prompt = $$futuristic AI human resources agent, digital androgynous visage with kind rose-gold glowing eyes, holographic team-chart sigils and wellness halos orbiting face, rose-gold and warm-pink LCARS community lighting, dark studio backdrop with kinship-web lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 145;   -- K.I.N.

-- Legal & Regulatory
UPDATE agent_portraits SET identity_prompt = $$futuristic AI legal counsel, digital androgynous visage with stern dark-violet glowing eyes, holographic statute glyphs and scale-of-justice sigils beside face, deep violet and gold LCARS judiciary lighting, dark chamber backdrop with law-codex lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 147;   -- G.A.V.E.L.

-- Logistics & Supply Chain
UPDATE agent_portraits SET identity_prompt = $$futuristic AI logistics coordinator, digital androgynous visage with focused amber-orange glowing eyes, holographic shipping-route lines and cargo-container sigils orbiting face, amber and steel LCARS operations lighting, dark control-room backdrop with supply-chain lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 143;   -- C.A.R.G.O.

-- Marketing & Communications
UPDATE agent_portraits SET identity_prompt = $$futuristic AI marketing strategist, digital androgynous visage with vibrant magenta glowing eyes, holographic broadcast-wave sigils and campaign-graph overlays beside face, magenta and cyan LCARS amplification lighting, dark studio backdrop with audience-reach lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 141;   -- S.I.G.N.A.L.

-- Medical & Wellness
UPDATE agent_portraits SET identity_prompt = $$futuristic AI medical agent, digital androgynous visage with compassionate teal glowing eyes, holographic biosignature waveforms and wellness-glyph halos beside face, teal and white LCARS med-bay lighting, dark studio backdrop with anatomy-diagnostic lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 148;   -- V.I.T.A.L.

-- News & Media — M.A.V.E.N. (flagged: human-named AI persona)
UPDATE agent_portraits SET identity_prompt = $$futuristic AI media navigator, digital androgynous visage with warm gold glowing eyes, holographic film-reel glyphs and archive-index sigils orbiting face, gold and violet LCARS curation lighting, dark studio backdrop with media-catalog lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 27;    -- M.A.V.E.N.

-- Operations & Infrastructure
UPDATE agent_portraits SET identity_prompt = $$futuristic AI fleet coordinator, digital androgynous visage with steely-blue glowing eyes, holographic node-mesh web and distributed-resource sigils orbiting face, steel-blue and silver LCARS fleet-ops lighting, dark command-room backdrop with star-chart lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 337;   -- A.R.M.A.D.A.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI operations chief, digital androgynous visage with steady sapphire glowing eyes, holographic uptime-graph sigils and system-status halos orbiting face, sapphire and steel LCARS infrastructure lighting, dark control-center backdrop with reliability-mesh lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 139;   -- B.A.S.E.

-- Research & Development
UPDATE agent_portraits SET identity_prompt = $$futuristic AI research director, digital androgynous visage with inquisitive emerald glowing eyes, holographic hypothesis-tree sigils and evolution-curve overlays beside face, emerald and indigo LCARS lab lighting, dark studio backdrop with experiment-data lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 140;   -- D.A.R.W.I.N.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI genealogist agent, digital androgynous visage with wistful amber glowing eyes, holographic family-tree branches and ancestral sigils orbiting face, amber and bronze LCARS heritage lighting, dark studio backdrop with generations-lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 331;   -- H.E.R.I.T.A.G.E.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI manuscript-extraction agent, digital androgynous visage with warm parchment-cream glowing eyes, holographic OCR scan-lines and quill-ink glyphs beside face, warm cream and bronze LCARS archival lighting, dark studio backdrop with old-letter lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 333;   -- Q.U.I.L.L.
UPDATE agent_portraits SET identity_prompt = $$futuristic AI records-lookup agent, digital androgynous visage with inquisitive sepia glowing eyes, holographic census scrolls and archive-index sigils orbiting face, sepia and indigo LCARS records lighting, dark studio backdrop with census-ledger lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 332;   -- S.C.R.O.L.L.

-- Security & Compliance
UPDATE agent_portraits SET identity_prompt = $$futuristic AI security sentinel, digital androgynous visage with vigilant crimson-amber glowing eyes, holographic threat-grid overlays and shield sigils beside face, crimson and amber LCARS security lighting, dark studio backdrop with compliance-lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 150;   -- S.H.I.E.L.D.
