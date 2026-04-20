-- Migration 339b: Seed agent_portraits rows for 6 AI agents that never had
-- a portrait generated. Migration 339's UPDATE-based pattern was a no-op for
-- these because no row existed to update. Using INSERT ... ON CONFLICT so
-- re-running is safe (no-op if the row already exists from a prior gen).

INSERT INTO agent_portraits (agent_id, identity_prompt, approved, updated_at)
VALUES
  (331, $$futuristic AI genealogist agent, digital androgynous visage with wistful amber glowing eyes, holographic family-tree branches and ancestral sigils orbiting face, amber and bronze LCARS heritage lighting, dark studio backdrop with generations-lattice backdrop, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, false, NOW()),
  (332, $$futuristic AI records-lookup agent, digital androgynous visage with inquisitive sepia glowing eyes, holographic census scrolls and archive-index sigils orbiting face, sepia and indigo LCARS records lighting, dark studio backdrop with census-ledger lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, false, NOW()),
  (333, $$futuristic AI manuscript-extraction agent, digital androgynous visage with warm parchment-cream glowing eyes, holographic OCR scan-lines and quill-ink glyphs beside face, warm cream and bronze LCARS archival lighting, dark studio backdrop with old-letter lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, false, NOW()),
  (334, $$futuristic AI face-analysis agent, digital androgynous visage with geometric scan-grid overlaid across features, glowing green biometric landmark points tracing facial structure, emerald and teal LCARS identification lighting, dark studio backdrop with face-embedding cluster lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, false, NOW()),
  (335, $$futuristic AI restoration agent, digital androgynous visage with warm sepia glowing eyes, holographic ripple-effect scratches dissolving into restored imagery beside face, amber and bronze LCARS archive-repair lighting, dark studio backdrop with before-after photo lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, false, NOW()),
  (337, $$futuristic AI fleet coordinator, digital androgynous visage with steely-blue glowing eyes, holographic node-mesh web and distributed-resource sigils orbiting face, steel-blue and silver LCARS fleet-ops lighting, dark command-room backdrop with star-chart lattice, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$, false, NOW())
ON CONFLICT (agent_id) DO UPDATE SET
  identity_prompt = EXCLUDED.identity_prompt,
  updated_at      = NOW();
