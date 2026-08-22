-- 473_model_placement_log.sql — hardware utilization observer, Phase 1 (#5273)
--
-- WHY: model_service.gpu_placement_options() is "THE single placement decision
-- point, with one log line per call" — and that log line is the ONLY record.
-- `docker logs archie_scheduler | grep placement` is a ring buffer a restart
-- erases, so there is no history to query. The #5903 hunt burned four
-- hypotheses reaching a fact one SELECT would have returned.
--
-- This table persists the decision that function ALREADY computes. No new
-- probing, no new polling, no node-agent change.
--
-- VOLUME (measured 2026-08-21 over 6h of scheduler logs): 324 calls ≈ 54/hour
-- ≈ 1,300/day. At 30d retention ≈ 39k rows. Cheap; no partitioning needed.
--
-- ⚠️ A PLACEMENT IS PER-LOAD, NOT PER-REQUEST. KEEP_ALIVE=60m, so one 'cpu' row
-- means the model SAT in CPU mode serving everything that arrived during that
-- span. The useful metric is TIME-IN-STATE, derived with lead() over
-- consecutive rows per model — a raw count understates it badly.

CREATE TABLE IF NOT EXISTS model_placement_log (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    model            TEXT         NOT NULL,
    decision         TEXT         NOT NULL,   -- 'gpu' | 'cpu'
    reason           TEXT         NOT NULL,   -- 'resident' | 'comfyui_reserved'
                                              -- | 'budget_fit' | 'budget_short'
                                              -- | 'vram_unknown'
    budget_gb        NUMERIC(6,2),            -- NULL where the branch does not compute it
    needed_gb        NUMERIC(6,2),
    resident_vram_gb NUMERIC(6,2),
    node_name        TEXT,                    -- hub today; carried so this can generalise
    detail           TEXT                     -- exception text on 'vram_unknown', else NULL
);

-- Time-ordered scans (the retention prune + every "last N hours" query).
CREATE INDEX IF NOT EXISTS idx_mpl_created
    ON model_placement_log (created_at DESC);

-- Per-model history — this is the index the time-in-state lead() window uses.
CREATE INDEX IF NOT EXISTS idx_mpl_model_created
    ON model_placement_log (model, created_at DESC);

-- Partial index for the fail-open branch. 'vram_unknown' means placement was
-- GUESSING — an exception-driven CPU demotion is indistinguishable from a
-- deliberate one in the logs, and on this pre-AVX2 Xeon a 7B on CPU cannot
-- finish inside the deadline (guaranteed failure, not a slow path — #5623).
-- Expected to be a tiny fraction of rows, so a partial index stays small.
CREATE INDEX IF NOT EXISTS idx_mpl_vram_unknown
    ON model_placement_log (created_at DESC)
    WHERE reason = 'vram_unknown';

COMMENT ON TABLE model_placement_log IS
    'Append-only record of every GPU-vs-CPU model placement decision (#5273). '
    'Written by services/placement_telemetry.record_placement from the single '
    'decision point in model_service.gpu_placement_options. A row is one LOAD, '
    'not one request — derive time-in-state with lead(), never a raw count. '
    'Pruned age-only by dispatch_retention_service (retention:mpl_keep_days).';
