# Verifier Batch 2 — 4 critical/high findings (2026-06-08)

## V5 — Global `_MODEL_LOAD_LOCK` serializes all warm-boots → **CONFIRMED, HIGH**
- `model_service.py:34` single module-global `_threading.Lock()` (comment :29-31: prevents CUDA frag, "regardless of caller"). NOT keyed by host; no per-host dict exists.
- `:393` `acquire(timeout=150)` at top of `ensure_model_ready` (before host branching); `:397-400` held across the WHOLE body via try/finally incl. `_fetch_ps` warm-check (:419) AND `load_model` (:470, urlopen timeout 600s).
- Even the already-warm fast path acquires it → warm checks serialize too. One slow remote load blocks all hosts.
- **Fix correct:** per-host lock keyed on `host:port`. The hub-CUDA rationale does NOT extend to remote CPU nodes or separate-GPU Starships; the warm path needs no lock at all.

## V6 — `current_load` broken/re-inflating + used to route AND display → **CONFIRMED, HIGH**
- **Decisive:** last 10 min — node 115 (Defiant) ran **95** executions with `current_load=6`; node 93 (Outpost-US) ran **11** with `current_load=49`. Counter is **inverted vs reality**.
- Live now: Outpost-US=49, Runabout=12, Beacon/Defiant=6, Hub=0 (max_concurrent=5 → 49 is 10× over capacity, impossible for a real running count).
- Writers: `fleet_node_routes.py:2513` `+1` (decrement `:2558` on a SEPARATE completion endpoint → leaks on error/abandon); `ai_bridge/node_router.py:264` `+5 cap 100` (different scale, "reset by heartbeat" but unreliable).
- Used as sort key `model_dispatch_service.py:74,126` `ORDER BY … current_load ASC` (biases AGAINST the least-loaded node) + displayed `fleet_dashboard_routes.py:2060,2328` + `fleet_node_routes.py:746` (ARMADA gauge).
- **Fix:** recompute live (`COUNT(*) task_execution_log WHERE node_used_id=… AND completed_at IS NULL AND created_at>now()-2min`) for both the sort key and the gauge; unify the two writers to one scale.

## V7 — Synchronous hub warmup stalls under the lock → **CONFIRMED (worse than claimed), HIGH**
- `fleet_jobs.py:199-263` `warmup_fleet_models()` = 9 capability pings via `ThreadPoolExecutor(max_workers=3)`, `as_completed(timeout=90)`, `IntervalTrigger(20min)`. Routes `dispatch()` → `department_dispatcher.py:3497 ensure_model_ready` → global lock.
- **Live (3h, 27 rows): avg 122,398 ms / max 513,267 ms** — HIGHER than the audited 89k/400k. Heavy models: **`mistral:7b` avg 299k / max 513k** + `gemma3:12b` avg 252k (audit wrongly named "deepseek-coder 16b"). Worst node_used_id = NULL (hub-side, avg 325k).
- ⚠️ `fleet_model_warmup` job has **no `max_instances=1`/`coalesce`** → an 8-min cycle overlaps the next 20-min trigger.
- **Fix:** drop the synchronous ping loop (the deterministic `_kin_fleet_warmth_policy` already enqueues per-node warmth via the queue) OR per-host lock + `max_instances=1, coalesce=True`.

## V8 — Hub iterated first → small CPU work piles on the hub → **CONFIRMED, MEDIUM**
- `model_dispatch_service.py:101` `result = {m: [None] …}` seeds hub (None) FIRST; `:150` nodes appended → list is `[hub, outpost_a, …]`. Worker (`:1249-1254`) iterates in order, hub claims up to `MAX_TASKS_PER_MODEL=8` before any outpost.
- **Live (1h): `qwen2.5:1.5b` hub(NULL)=383 (~42%)** vs outposts 127=148,125=116,93=92,126=90,128=70,120=10 — hub > next three outposts combined, for exactly the models that should run on outposts.
- **Fix:** for non-`prefer_gpu` models put hub LAST (or round-robin the node list per cycle); keep hub-first only for GPU-required models.

---
**Batch-2 net:** 4/4 CONFIRMED (V5/V6/V7 HIGH, V8 MEDIUM). Global lock + current_load + sync-warmup-stall are the systemic trio; hub-first is a placement tax. All four point at the same fix set: **per-host lock + recompute current_load + retire the sync warmup in favor of the queue keeper + outpost-first for small models.**
