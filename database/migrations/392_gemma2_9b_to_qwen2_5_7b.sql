-- Migration 392: Switch gemma2:9b agents to qwen2.5:7b
-- gemma2:9b causes "llama runner process terminated: exit status 2" on hub Ollama.
-- qwen2.5:7b is stable, GPU-resident on hub, and handles research/analysis tasks well.
-- Affected agents: S.C.R.O.L.L. (332), H.E.R.I.T.A.G.E. (331), A.R.M.A.D.A. (337)
-- Applied: 2026-05-22

UPDATE agents
SET model = 'qwen2.5:7b', updated_at = NOW()
WHERE id IN (331, 332, 337)
  AND model = 'gemma2:9b';
