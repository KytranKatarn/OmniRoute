-- Migration 354: Fix agent model assignments
-- Resolves hardware constraints (Quadro M4000 8GB VRAM) + A.R.C.H.I.E. model decision
--
-- A.R.C.H.I.E.: dolphin3-8k → qwen2.5:7b
--   Reason: qwen2.5 has stronger business reasoning. dolphin3's unconstrained
--   behaviour was the goal, but A.R.C.H.I.E.'s system_prompt + C.R.E.E.D. already
--   handle that. qwen2.5 is proven on this platform (S.I.G.N.A.L., P.R.O.C.U.R.E.).
--
-- D.A.R.W.I.N.: phi4:14b → gemma2:9b
--   Reason: phi4:14b cannot load on 8GB VRAM (exit status 2). gemma2:9b
--   is the best research reasoning model that fits.
--
-- G.A.V.E.L.: phi4:14b → mistral:7b
--   Reason: same VRAM constraint. mistral:7b has strong legal text comprehension.
--
-- P.R.O.B.E.: deepseek-coder-v2:16b → qwen2.5-coder:7b
--   Reason: deepseek-coder-v2:16b is not installed in Ollama on this host.
--   qwen2.5-coder:7b is installed, fits in VRAM, appropriate for platform reliability.

UPDATE agents SET model = 'qwen2.5:7b'        WHERE name = 'A.R.C.H.I.E.';
UPDATE agents SET model = 'gemma2:9b'          WHERE name = 'D.A.R.W.I.N.';
UPDATE agents SET model = 'mistral:7b'         WHERE name = 'G.A.V.E.L.';
UPDATE agents SET model = 'qwen2.5-coder:7b'   WHERE name = 'P.R.O.B.E.';
