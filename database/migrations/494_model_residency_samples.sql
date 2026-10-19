-- 494_model_residency_samples.sql — actual model residency, sampled (#5273 / #6106)
--
-- WHY: model_placement_log records the placement DECISION. It cannot see the
-- OUTCOME: gpu_placement_options() returned {} ("gpu") for qwen2.5:7b while the
-- live runner sat at size_vram=0 on CPU, because Ollama does not move a live
-- runner when a request merely omits num_gpu (#5328). Measured 2026-10-19:
-- qwen2.5:7b succeeded 88.7% over 24h, bimodal by hour (~100% at 20-60s vs
-- 37-80% at 250-600s). Nothing recorded which hours it was on CPU, so the cause
-- had to be inferred from log lines.
--
-- This table stores what Ollama's /api/ps ACTUALLY reports, one row per loaded
-- model per sample (every 5 min, piggybacking the existing
-- ollama_lifecycle_telemetry job -- no second poller). Join it to
-- model_placement_log to compare intent against reality.
--
-- VOLUME: ~6 loaded models x 288 samples/day ~ 1.7k rows/day; 30d retention.
--
-- Additive and idempotent.

CREATE TABLE IF NOT EXISTS model_residency_samples (
    id               BIGSERIAL PRIMARY KEY,
    sampled_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    node_name        TEXT         NOT NULL DEFAULT 'hub',
    model            TEXT         NOT NULL,          -- as Ollama names it (may carry :latest)
    size_gb          NUMERIC(6,2) NOT NULL,          -- total resident footprint
    size_vram_gb     NUMERIC(6,2) NOT NULL,          -- portion in VRAM; 0 = fully on CPU
    seconds_remaining INTEGER,                       -- KEEP_ALIVE clock; negative = past expiry
    modelfile_cpu_pin BOOLEAN                        -- Modelfile pins num_gpu 0 (CPU by design); NULL = unknown
);

CREATE INDEX IF NOT EXISTS idx_mrs_sampled
    ON model_residency_samples (sampled_at DESC);
CREATE INDEX IF NOT EXISTS idx_mrs_model_sampled
    ON model_residency_samples (model, sampled_at DESC);

-- STRANDED = the router meant GPU, the model is resident, and it holds no VRAM.
-- Strict on purpose (needs a prior 'gpu' decision for the model): a model with no
-- decision on record, a CPU decision, or a Modelfile CPU pin is NOT stranded --
-- qwen25-classify reads size_vram=0 forever by design, and flagging it is the
-- exact false positive that made the keep-warm unload it 54x/day.
CREATE OR REPLACE VIEW v_model_residency_stranded AS
SELECT s.id,
       s.sampled_at,
       s.node_name,
       s.model,
       s.size_gb,
       d.decision   AS last_decision,
       d.reason     AS last_reason,
       d.created_at AS decided_at
FROM model_residency_samples s
JOIN LATERAL (
    SELECT p.decision, p.reason, p.created_at
    FROM model_placement_log p
    WHERE regexp_replace(p.model, ':latest$', '') = regexp_replace(s.model, ':latest$', '')
      AND p.created_at <= s.sampled_at
    ORDER BY p.created_at DESC
    LIMIT 1
) d ON true
WHERE s.size_vram_gb = 0
  AND s.modelfile_cpu_pin IS NOT TRUE
  AND d.decision = 'gpu';
