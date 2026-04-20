-- Migration 338: Rewrite identity_prompt for 8 AI acronym agents with sci-fi
-- LCARS aesthetic. Drops corporate-headshot template that was baked in by a
-- prior seeder — AI acronym agents should read as futuristic digital entities,
-- not LinkedIn photos. Humans keep the corporate+ethnicity pattern (Phase 3).
--
-- Idempotent: UPDATEs are targeted by agent_id.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI journalism agent, digital androgynous visage with flowing ink-blue data streams cascading from temples, holographic paragraph glyphs floating beside face, purple and teal LCARS interface panels glowing in background, dark Federation bridge aesthetic, cinematic rim lighting, photorealistic 3D render, high detail, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 23;   -- I.N.K.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI market analyst, digital androgynous visage with glowing cyan eyes and subtle circuit tracery along cheekbones, holographic stock-ticker data streams rotating beside face, green and cyan LCARS financial-grid overlays, dark operations-center background with scrolling numeric data, cinematic studio lighting, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 32;   -- M.A.R.K.E.T.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI fact-verifier, digital androgynous visage with piercing cold-blue glowing eyes, holographic truth-scan overlay with verification sigils and checkmark halos, icy blue and white LCARS lighting, dark studio with data lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 48;   -- F.A.C.T.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI bias-analyzer, digital androgynous visage with split dual-tone lighting cognitive overlay, magenta and violet LCARS lighting with spectrum-analysis holographics beside face, dark studio background with opposing thought-pattern waveforms, cinematic lighting, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 49;   -- B.I.A.S.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI broadcast director, digital androgynous visage with warm gold glowing eyes, holographic signal waves radiating outward from forehead, orange and amber LCARS broadcast-array accents, dark studio background with transmission grid backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 58;   -- P.U.B.L.I.S.H.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI editor agent, digital androgynous visage with glowing amber eyes, holographic composition grid and floating text glyphs arranged beside face, warm amber and bronze LCARS lighting, dark studio background with manuscript-lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 79;   -- D.R.A.F.T.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI authentication agent, digital androgynous visage with piercing green glowing eyes, holographic validation grid with checkmark halos and biometric sigils beside face, emerald and teal LCARS security lighting, dark studio background with verification-lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 116;  -- V.E.R.I.F.Y.

UPDATE agent_portraits SET identity_prompt = $$futuristic AI archivist agent, digital androgynous visage with warm amber glowing eyes, ember-like particles and floating glyphs around face, warm orange and red LCARS archival lighting, dark studio background with ancient-to-future glyph lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, updated_at = NOW() WHERE agent_id = 126;  -- E.M.B.E.R.
