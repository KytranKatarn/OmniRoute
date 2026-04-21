-- Migration 343: Seed sci-fi identity_prompt for P.R.O.B.E. (id 340).
--
-- P.R.O.B.E. (Platform Reliability, Observation, Browser-testing & Evaluation)
-- was accidentally excluded from Phase 2 (PR #227) — the audit assumed it was
-- already sci-fi like V.I.G.I.L., but it had no identity_prompt at all and
-- pointed avatar_url at a non-existent /static/media/portraits/probe.png.
--
-- This migration seeds the missing prompt + clears the bad avatar_url so a
-- regen run produces a proper sci-fi portrait matching the canonical 17 +
-- specialist set. Idempotent UPSERT.

INSERT INTO agent_portraits (agent_id, identity_prompt, approved, updated_at)
VALUES (340,
  $$futuristic AI quality-assurance sentinel, digital androgynous visage with piercing green diagnostic eyes, holographic test-grid overlays and validation checkmarks orbiting face, emerald and cyan LCARS browser-test lighting, dark control-room backdrop with regression matrix and Playwright trace lines, cinematic rim light, photorealistic 3D render, 8k, sharp focus$$,
  false, NOW())
ON CONFLICT (agent_id) DO UPDATE SET
  identity_prompt = EXCLUDED.identity_prompt,
  updated_at = NOW();
