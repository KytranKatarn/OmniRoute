# Dispatch / Warm-Boot / Orchestration Review — 2026-06-08

Solo review (after a workflow over-fan-out failed — 4/24 agents). Grounded in code + live DB
verified this session. Scope: the full dispatch → warm/cold-boot → routing → execute → track
loop, whether this session broke anything, and the optimal warm-fleet design.

---

## 0. Headline

- **Production is healthy.** Last 20 min: `qwen2.5:7b` **199 success / 0 fail**, `qwen2.5:1.5b`
  287/0, all `success=t`, queue had 0 failures and **no zombies**. The 3 dispatch fixes
  (#1516/#1517/#1518) **work in production**. No mechanic is broken.
- **Tracking — CORRECTED (see batch-2):** the main `dispatch()` path is fully tracked, but the
  **queue-drain path's dispatches/tokens NEVER reach `task_execution_log`** → invisible in Token
  Economy + ARMADA. This is a **pre-existing gap, NOT a regression** from this session. (My earlier
  "INTACT" was based on TEL rows that actually came via `dispatch()`, not the queue worker.)
- The warm-set keeper **already exists** (`_kin_fleet_warmth_policy`, K.I.N.-attributed) but is
  **~50% broken** (48% of warmth tasks expire unclaimed). So the work is **fix the keeper + add a
  per-host model-load lock + log the queue path to TEL** — not build from scratch.

---

## 1. End-to-end workflow map (as it works today)

```
caller
 ├─ sync path:  department_dispatcher.dispatch() → request_work()
 │                → coordinator.select_agent (skill) → find_best_node_for_model (score_node_for_model)
 │                → ensure_model_ready → _dispatch_to_node / _execute_llm → task_execution_log
 └─ async path: INSERT dispatch_pending_queue (status=queued)
                   ↓  [model_dispatch_worker — archie_scheduler, every 15s]
        reconcile_fleet_models (≤60s) → _expire_stale_tasks
        → _get_all_warm_nodes_for_models()              # {model: [node_ids, None=hub]}
            • DRP guard: ARCHIE_DR_MODE=1 → {} + drop CPU nodes
            • can_node_run_model(node, model)  (FIT-only, #1518)  → drop unfit nodes
        → for each warm (model,node): _claim_tasks → _CPU_EXECUTOR.submit(_execute_task, node)
        → _claim_preferred_node_tasks (preferred_node_id rows, 2/cycle)
                   ↓  [_execute_task in a thread]
        node:  resolve mesh_ip+port → disp.ensure_model_ready(agent, model, {hostname,port})  (#1516)
               if ready → _dispatch_to_node(POST /api/generate) else _requeue_cold
        hub:   ensure_model_ready(..,None) → _execute_llm
                   ↓
        ensure_model_ready (model_service):
            acquire _MODEL_LOAD_LOCK (GLOBAL, 150s)            ← see §3.1
              _fetch_ps(host): loaded? → ready (ms)            ← WARM = cheap
              else ensure_capacity(HUB-only) + load_model(model, ollama_url)  (#1517 warms TARGET host)
            release lock
                   ↓
        result → _mark_done/_mark_failed (dispatch_pending_queue)
               + task_execution_log row (model_used, tokens, success, node_used_id, module_source)
```

Warm vs cold: a **warm** model = `/api/ps` reports it loaded → `ensure_model_ready` returns in
milliseconds. A **cold** model = `load_model` POSTs an empty `/api/generate` (keep_alive 10m) to
warm it — and that load is what holds the global lock.

---

## 2. Tracking integrity — VERDICT: ✅ INTACT

- `task_execution_log` receives every dispatch with `model_used`, `prompt_tokens`/`completion_tokens`,
  `success`, `node_used_id`, `module_source`. Verified live: queue-drained 7B node dispatches show
  up as `qwen2.5:7b success` rows (199 in 20 min) → the async path logs correctly.
- **Token Economy** (`code_health_routes.py /api/code-health/token-usage`) and **ARMADA dispatch
  traffic** (`dispatch_routes.py`, by source/agent/model/node) both read `task_execution_log` → both
  still populated.
- This session's changes (#1516/#1517/#1518) touched routing/warm-boot, **not** the logging path →
  no tracking regression.
- One caveat: **`current_load`** (a DIFFERENT column) is broken (§3.2) and feeds the ARMADA *node
  load* widget + the sync scorer — it shows garbage (Citadel 22 vs real ~0). It does **not** affect
  token/dispatch counts, only the load gauge.

---

## 3. Confirmed issues

| # | Issue | Kind | Sev | Evidence | Fix |
|---|-------|------|-----|----------|-----|
| 3.1 | **Global `_MODEL_LOAD_LOCK`** held for the whole load (≤600s); one slow CPU cold-load (~84s) blocks ALL fleet dispatch | risk (latent) | HIGH | `model_service.ensure_model_ready` acquire(timeout=150); Citadel un-gate live-stalled the queue this session | **Per-host lock** (dict keyed by host) |
| 3.2 | **`current_load` counter broken** — increment `fleet_node_routes.py:2513`, decrement skipped on error paths `:2558`, plus `+5/cap-100` writer `ai_bridge/node_router.py:264` | broken | MED | live Citadel=22/LT=17 vs real load ~0 | fix decrement on all exits + unify scale, OR drop from scoring |
| 3.3 | **No proactive warm-set** — load-on-dispatch + KEEP_ALIVE eviction → frequent cold-loads → (via 3.1) contagious | optimization | MED | no keeper job exists; `node_provisioning.recommend()` computes a set but nothing keeps it resident | **warm-set keeper** job |
| 3.4 | **ADR-017 dispatch-to-ALL-warm-nodes** mixes slow CPU with fast GPU as co-equal | optimization | MED | `model_dispatch_worker` loops every warm node per model | **CPU-as-overflow** (only when GPU saturated) |
| 3.5 | Sync path still scores on broken `current_load` (`score_node_for_model`) | risk | LOW | worker is now immune (fit-only #1518); sync path not | same as 3.2 |

**Regressions from THIS session: NONE confirmed.** The un-gate→stall was caught and reverted same
session; #1516/#1517/#1518 are live and production is 100% success on 7B. `load_model`'s
remote-node path has no capacity guard (ensure_capacity is hub-only) — *acceptable* because the
fit-gate (`can_node_run_model`) already prevents routing a model to a node that can't hold it; the
node would just fail the load → bounded re-queue. Worth a watch, not a regression.

---

## 4. Optimal warm-fleet orchestration (the design)

**Principle:** spend cheap idle RAM to hold models warm so dispatch (almost) never cold-loads;
make cold-loads (when they happen) cheap and *local*; let K.I.N. tune it by demand + welfare.

### 4.1 Foundation (unblocks everything)
- **Per-host `_MODEL_LOAD_LOCK`** — `model_service`: replace the single global lock with
  `defaultdict(Lock)` keyed by `host:port`. A Citadel load then serializes only Citadel; the hub +
  Starships keep flowing. Removes the §3.1 landmine entirely.
- **Warm-set keeper** — a low-frequency job (e.g. every 5–10 min, or fold into `kin_workload_monitor`)
  that, per online node, ensures its TARGET set is resident: `load_model(m, node_url)` with a long
  keep-alive + periodic re-ping, bounded by the node's RAM/VRAM and the systemd/docker limits we set.
  Reuse `node_provisioning.recommend()` for the target set. Skip nodes in DR mode.

### 4.2 Per-node warm sets (bounded by the limits we set this session)
| Node | RAM / VRAM | Warm set | `OLLAMA_MAX_LOADED` |
|------|-----------|----------|---------------------|
| Hub | 128GB / Quadro 8GB | current 6 (fine) | 6 |
| Starship-246 | 29GB / RTX3070 8GB | `qwen2.5:7b`(GPU) + `1.5b` + `3b` | 3 |
| Starship-245 | 11.7GB / RTX3050 4GB | `1.5b`(GPU) + `3b`(CPU) | 2 |
| **Citadel** | 31GB / no GPU (DR) | `1.5b` + `3b` + embed; **optional `7b` resident** → then it's a *no-cold-load overflow* helper (under the 12G Ollama cap) | 2→3/4 |
| Outposts | 7.8GB / no GPU | `1.5b` + embed | 2 |

### 4.3 Routing: CPU as **overflow**, not co-equal
- 7B prefers the fastest GPU (RTX) — already true via `gpu_perf_weight` (#1511).
- Only spill 7B to a **warm** big-RAM CPU node (Citadel) when GPU nodes are saturated — never route
  routine 7B to cold CPU. Implement as a worker-side check: include a CPU node for a `prefer_gpu`
  model only if (a) it's warm for that model AND (b) all GPU candidates are at capacity.

### 4.4 K.I.N. ownership
- `kin_workload_monitor` (5-min, already token-based) becomes the **warm-set tuner**: read hot
  models/capabilities per node/region from `task_execution_log`, raise/lower each node's warm set,
  gate by welfare, and emit `propose_hire`/provision signals when warm capacity is exhausted.
- This makes warm/cold-boot a *scheduled, observable, welfare-gated* decision — the "optimal
  orchestration" goal.

---

## 5. Prioritized action plan

- **P0 — safety (done):** production healthy; Citadel stays gated `max_model_gb=4` until 4.1 lands.
  Nothing to fix.
- **P1 — foundation:**
  1. Per-host `_MODEL_LOAD_LOCK` in `model_service.py`. *Accept test:* two cold loads on different
     hosts run concurrently; a Citadel load no longer blocks a hub 1.5b dispatch.
  2. Warm-set keeper job. *Accept test:* after a KEEP_ALIVE gap, the target set is still resident
     (`/api/ps` shows it) → next dispatch is warm, not cold.
- **P2 — warm sets + routing:**
  3. Per-node warm sets + `OLLAMA_MAX_LOADED_MODELS` bumps (node env / OTA — **owner approval**,
     remote nodes).
  4. CPU-as-overflow gate in `fleet_resource_router` / worker. *Accept test:* 7B only lands on
     Citadel when both Starships are busy.
- **P3 — K.I.N. + cleanup:**
  5. `current_load` writer fix (decrement on all exits + unify scale) — `fleet_node_routes.py`,
     `ai_bridge/node_router.py`.
  6. K.I.N. demand-driven warm-set tuning in `kin_workload_monitor`.

**Most important next step:** P1.1 (per-host lock) — it removes the only true landmine and is the
prerequisite for safely using any CPU node (incl. Citadel) as a warm helper.

---

*Refs: KB #271848 (3-bug dispatch fix), #271849 (node hardening). PRs #1516/#1517/#1518.
Live verified 2026-06-08.*
