# Verifier Batch 3 — final 4 findings (2026-06-08)

## V9 — DRP guard fallback still warms on the hub in DR mode → **CONFIRMED, LOW**
- `_get_all_warm_nodes_for_models` DR guard is correct (`model_dispatch_service.py:100-101` `result={}` if dr_mode; `:134-135` drop CPU nodes). But in DR `all_warm_by_model` is empty → `total_executed==0`.
- **Unguarded fallback `:1290-1307`:** `if total_executed==0:` → `_get_highest_priority_queued_model()` (`:1174-1202`, NO DR check) → `_ensure_ram_for_model` (evicts hub RAM) → `ensure_model_ready("model_dispatch_worker", next_model)` warms on hub/local. DR mode *guarantees* `total_executed==0`, so the guard makes the fallback MORE likely to fire.
- LOW (only during a real failover). **Fix:** `if total_executed==0 and os.getenv("ARCHIE_DR_MODE","0")!="1":` around the fallback (or early-return the worker in DR).

## V10 — Remote warm-boot has NO node capacity guard → **CONFIRMED, MEDIUM**
- `model_service.py:451-453` Step-2 `ensure_capacity` gated `if target_host is None` (hub-only, intentional comment); `:470` remote `load_model(model, ollama_url)` runs with no node check; `load_model` (:249-285) just POSTs `/api/generate`. `department_dispatcher.py:8774` second guard ALSO hub-only → remote path has neither.
- MEDIUM (not HIGH): preferred nodes usually chosen by capable upstream routing; Ollama enforces `OLLAMA_MAX_LOADED_MODELS` (LRU evict, not crash); worst case = swap latency + `ready=False` → bounded re-queue.
- **Fix:** in `_ensure_model_ready_locked`, when `target_host` set, run `can_node_run_model(node_row, model)` before `load_model` (look up the `remote_nodes` row for vram/ram/max_model_gb) → on fail return not-ready → re-queue. Same predicate already trusted on the queue path; closes the preferred-node gap (V3) too.

## V11 — ADR-017 parallel drain has no speed weighting → **PARTIALLY CONFIRMED, MEDIUM**
- Worker claims equal per-node cap (`MAX_TASKS_PER_MODEL=8`, `:1246-1260`); `_claim_tasks` (:403-433) flat `ORDER BY priority,queued_at` — no speed term. `gpu_perf_weight` lives only in the SYNC path (`fleet_resource_router.py:63/179`), not the worker.
- BUT nodes are pre-sorted `bridge_priority DESC, current_load ASC` (:126) → faster/preferred node appended first claims its batch first (partial fill-fastest). Equal split only when queue > n_nodes×8.
- Live 7B (24h): node 115 RTX3070 = **2882 @ 7s**, node 120 RTX3050 = 1017 @ 59s, hub Quadro = 1605 @ 150s. Fast node already carries the largest share → "drags toward slowest" is OVERSTATED; it's a long tail, not collapse.
- **Fix (optimization):** weight `per_node_limit` by `gpu_perf_weight` / inverse avg `duration_ms`, or cap slow-node claims (RTX3050/Quadro 7B → 2-3).

## V12 — "80% colocation pins 7B to slow hub Quadro" → **REFUTED (already fixed by #1511)**
- Math (`fleet_resource_router.py:175-179`): 7B GPU-fit score = base 1.0 + tier 1.0 + 1.2×gpu_perf. Hub Quadro perf 0.12 → **2.144**; RTX3070 perf 1.0 → **3.200**. Colocation keeps home only if `home ≥ 0.80×best` → 2.144 < 2.56 → **RTX wins, hub NOT pinned.**
- Hub-resident agents have `node_db_id=NULL` (`department_dispatcher.py:708`) → colocation branch never fires for them anyway.
- Live (6h hourly): hub got 7B only through 13:00; **from 14:00→17:00 hub = ZERO 7B**, 100% on RTX 115 (~5s) + 120 (~50s). #1511 is live and working. `test_gpu_routing.py` guards it.
- **No fix needed.** Verification caught a stale finding.

---
**Batch-3 net:** V9 LOW, V10 MEDIUM, V11 MEDIUM(partial), **V12 REFUTED**. The fixes for V9/V10 converge with the rest (gate fallback on DR; reuse `can_node_run_model` for the remote/preferred path).
