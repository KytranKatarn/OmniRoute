-- Fleet rebalance (2026-08-21, task: dispatch-placement rebalance across the cluster).
--
-- MEASURED PROBLEM: fact_check (qwen2.5:7b) baseline over 7 days —
--   Archie Starbase (hub)          10134 runs, 78% success, 319 busy-h
--   Starship-246 (RTX 3070 8GB)     4231 runs, 99% success,  75 busy-h
--   Starship-245 (RTX 3050 4GB)     1207 runs, 99% success,  28 busy-h
-- The scorer in services/fleet_resource_router.py already heavily de-prefers the
-- hub for prefer_gpu models (HUB_HEAVY_PENALTY, gpu_perf_weight) and correctly
-- ranks USS-246 >> hub >> USS-245 for qwen2.5:7b (measured live: 2.80 / 0.44 / 0.10).
-- Despite that, the hub absorbed 78% of the work — root cause is
-- `_node_at_cap()` in department_dispatcher.py: with the batch reserve
-- (platform_settings 'dispatch:node_cap:batch_reserve', default 1), USS-246's
-- effective concurrency was max(3-1,1)=2 and USS-245's was max(1-1,1)=1 (i.e.
-- ALWAYS at cap whenever a single job was running). The hub is EXCLUDED from
-- this cap check entirely (bridge_priority >= 100) and so absorbs everything
-- the (badly undersized) Starships bounce.
--
-- This raises the two Starship caps to values that actually reflect their
-- hardware (USS-246 already runs 3 distinct 7B/mistral models concurrently in
-- practice, matching its Ollama MAX_LOADED_MODELS=6; USS-245 is the weaker
-- RTX 3050 4GB card, so raised more conservatively). Citadel and the CPU
-- outposts (US/Lithuania/Singapore/UK) are left untouched — this task
-- explicitly asked not to increase Citadel's share, and the outposts are not
-- the bottleneck (they were never overloaded; they are simply not assigned
-- 7B work, correctly, since it doesn't fit their hardware).
--
-- REVERT: run the "OLD VALUE" UPDATE lines commented below.

-- Starship - Defiant - USS-246 (id=115): 3 -> 5
UPDATE remote_nodes SET max_concurrent = 5 WHERE id = 115 AND node_name = 'Starship - Defiant - USS-246';
-- REVERT: UPDATE remote_nodes SET max_concurrent = 3 WHERE id = 115;

-- Starship - Runabout - USS-245 (id=120): 1 -> 3
UPDATE remote_nodes SET max_concurrent = 3 WHERE id = 120 AND node_name = 'Starship - Runabout - USS-245';
-- REVERT: UPDATE remote_nodes SET max_concurrent = 1 WHERE id = 120;

-- Fleet-wide model hardware blocklist (services/fleet_resource_router.py
-- model_hardware_blocklist()): gemma3:12b's 15.6GB footprint fits no GPU in
-- this fleet (hub 12GB largest single card / USS-246 8GB / USS-245 4GB), so it
-- only ever runs CPU-demoted — measured 56% success fleet-wide. The code
-- already falls back to this exact default when the row is absent; this row
-- makes the current policy visible + owner-editable in platform_settings
-- without a deploy. Clear the value (empty string) to un-block, or DELETE the
-- row to fall back to the compiled-in default (same value).
INSERT INTO platform_settings (key, value, value_type, description, updated_at)
VALUES (
    'dispatch:model_blocklist',
    'gemma3:12b',
    'string',
    'Comma-separated model names disqualified fleet-wide (owner hardware-fit decision, not a per-node cap). See services/fleet_resource_router.py model_hardware_blocklist(). 2026-08-21 fleet rebalance.',
    NOW()
)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description, updated_at = NOW();
-- REVERT: DELETE FROM platform_settings WHERE key = 'dispatch:model_blocklist';

-- ---------------------------------------------------------------------------
-- AMENDMENT (same day, after Kytran challenged the gemma3:12b block).
--
-- USS-246 sat at max_model_gb=16 while gemma3:12b requires 24, so
-- can_node_run_model() refused it there. Yet task_execution_log shows the node
-- ran that model 2,918 times at 95% over 30 days (avg 38.4s) — those reached it
-- via ModelQueuePlanner, which bypasses the capacity predicate (#5809). The
-- predicate was wrong about this node; the measured behaviour was right.
--
-- Cap 26 chosen per the fleet.md open-interval rule: admits gemma3:12b (24) with
-- margin, and there is no model between 24 and 26 to accidentally admit.
-- Concurrency trimmed 5 -> 4 in the same statement: a 24GB resident model on a
-- 29.4GB node needs the slot count to come down, or several DIFFERENT large
-- models could land together. (Same-model bursts are fine — NUM_PARALLEL=1 on
-- this node serialises them and Ollama shares the weights.)
--
-- PREDICTION (state it before, per fleet.md step 6): gemma3:12b traffic shifts
-- off the hub toward USS-246, hub gemma3 success rises from 52% as the node
-- absorbs the load it is good at, and USS-246 stays at/near its 95%. If USS-246's
-- gemma3 success DROPS below ~85%, the cap is too generous — revert below.
UPDATE remote_nodes
   SET extra_capabilities = jsonb_set(extra_capabilities, '{max_model_gb}', '26'),
       max_concurrent     = 4
 WHERE node_name ILIKE '%246%';

-- REVERT (restores the pre-amendment state, NOT the pre-rebalance state):
-- UPDATE remote_nodes
--    SET extra_capabilities = jsonb_set(extra_capabilities, '{max_model_gb}', '16'),
--        max_concurrent     = 5
--  WHERE node_name ILIKE '%246%';
--
-- Citadel deliberately NOT touched (cap stays 6) despite 31.3GB RAM: it serves
-- what-the-fact.com plus four other live products, so its RAM headroom is not
-- spare inference capacity. Owner's call, 2026-08-21.
