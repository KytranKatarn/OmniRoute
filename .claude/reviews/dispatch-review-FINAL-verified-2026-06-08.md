# FINAL — Dispatch / Warm-Boot / Orchestration Review (verified) — 2026-06-08

**Coverage:** 6 subsystem audits (4 recovered + 2 re-run) + **12 distinct findings independently
adversarially verified** (3 batches of 4). Production stayed healthy throughout. Companion files:
`*-recovered-agent-audits*`, `*-batch2-kin-tracking*`, `*-verify-batch1/2/3*`.

## Bottom line
- **No regression** from this session's PRs (#1516/#1517/#1518) — confirmed by multiple agents. The
  7B-to-fleet fix works in production.
- **Tracking is partially broken (PRE-EXISTING):** the queue-drain path's dispatches/tokens never
  reach `task_execution_log` → invisible in Token Economy + ARMADA (~1,382/day, ~209k tok). NOT
  caused by this session.
- The systemic root is a **single global model-load lock** + a **broken `current_load`** + a
  **synchronous warmup that stalls under that lock**. Fix those three and the warm-fleet works.

## Verified findings (severity-sorted; all re-checked against live code+DB)

| # | Finding | Verdict | Sev | Fix (file) |
|---|---------|---------|-----|-----------|
| V5 | Global `_MODEL_LOAD_LOCK` serializes ALL warm-boots; one slow load stalls the fleet | CONFIRMED | **HIGH** | per-host lock keyed on host:port (`model_service.py:34/393`) |
| V6 | `current_load` broken & **inverted** (node ran 95 tasks→load=6; ran 11→load=49); routes + ARMADA gauge | CONFIRMED | **HIGH** | recompute live from TEL/queue (`fleet_node_routes.py:2513/2558`, `node_router.py:264`, `model_dispatch_service.py:74/126`) |
| V7 | Synchronous hub warmup stalls under the lock — **avg 122s / max 513s** (mistral:7b 299s, gemma3:12b 252s) | CONFIRMED | **HIGH** | drop sync ping loop (kin_warmth owns it) + per-host lock + `max_instances=1` (`fleet_jobs.py:199/1103`) |
| V2 | Queue-drain path never writes `task_execution_log` → invisible in Token Economy + ARMADA | CONFIRMED | **HIGH** | call `_log_execution` (or TEL INSERT in `_mark_done`) from `_execute_task` (`model_dispatch_service.py`) |
| V3 | Preferred-node path bypasses the capacity gate → 7B pinned to a CPU node warm-boots there | CONFIRMED | **HIGH** | `can_node_run_model` check in `_execute_task` preferred branch (`:801-819`) |
| V4 | Fit gate vs sync scorer give OPPOSITE admission for CPU-7B (scorer conflates capacity+ranking) | CONFIRMED | MEDIUM | gate admission on `can_node_run_model` in `find_best_node_for_model`; score only ranks |
| V8 | Hub iterated first → ~42% of small-model work piles on the hub instead of idle outposts | CONFIRMED | MEDIUM | hub LAST for non-prefer_gpu models / round-robin (`model_dispatch_service.py:101/150/1249`) |
| V10 | Remote warm-boot has NO node capacity guard (ensure_capacity hub-only) | CONFIRMED | MEDIUM | reuse `can_node_run_model` before remote `load_model` (`model_service.py:451-470`) — same fix as V3 |
| V11 | ADR-017 parallel drain has no speed weighting (slow node gets equal share) | PARTIAL | MEDIUM | weight `per_node_limit` by `gpu_perf_weight`/inverse-latency (`:1246-1260`) — partial: order already front-loads fast node |
| V1 | `kin_warmth` keeper ~49% expire/fail (33 done/20 expired/10 failed/6h) | PARTIAL | LOW | claim cause was wrong (limit=4 not 2); fix TTL (≥10m) + KEEP_ALIVE-aware cadence; no-op pings, self-heal |
| V9 | DRP guard's `total_executed==0` fallback still warms a model on the hub in DR mode | CONFIRMED | LOW | gate fallback on `ARCHIE_DR_MODE` (`model_dispatch_service.py:1290-1307`) |
| V12 | "80% colocation pins 7B to slow hub Quadro" | **REFUTED** | — | already fixed by #1511 (RTX 3.20 > hub 2.144; live: hub=0 7B since 14:00) |

## Prioritized action plan (the optimal orchestration)

**P0 — nothing broken.** Production healthy; keep Citadel gated (`max_model_gb=4`) until P1.

**P1 — foundation (highest leverage):**
1. **Per-host `_MODEL_LOAD_LOCK`** (V5, also fixes the V7 cross-host stall). `model_service.py` — replace
   the single `Lock()` with a per-`host:port` lock dict; the already-warm path needs none.
   *Accept:* two cold loads on different hosts run concurrently; a Citadel load doesn't block a hub 1.5b.
2. **Log the queue path to TEL** (V2). *Accept:* queue-drained dispatches + tokens appear in Token
   Economy + ARMADA (TEL rows with `module_source` of the queue worker > 0).

**P2 — routing correctness + visibility:**
3. **Close the capacity bypass** — `can_node_run_model` on the preferred-node path (V3) AND the remote
   warm path (V10); unify fit/scorer admission (V4). One PR. *Accept:* a 7B pinned to a CPU node is
   rejected/re-queued, not warm-booted there.
4. **Fix `current_load`** (V6) — recompute live for the sort key + ARMADA gauge; unify the two writers.
   *Accept:* gauge matches reality (busy node high, idle low).
5. **Retire the synchronous hub warmup** (V7) — let `kin_warmth` own warmth; add `max_instances=1,
   coalesce=True`. **Hub-last for small models** (V8).

**P3 — warm-fleet tuning (the proactive cluster):**
6. Fix `kin_warmth` drain reliability + KEEP_ALIVE-aware cadence (V1); per-node claim speed weighting
   (V11); K.I.N. demand-driven warm-set width; gate the DRP fallback (V9).

**Single most important next step:** **P1.1 — per-host model-load lock.** It removes the systemic
stall, is the prerequisite for safely warm-booting more nodes (incl. Citadel), and unblocks the
warm-fleet vision. Small, well-scoped, high-impact.

---
*All 12 findings verified 2026-06-08. KB #271848/#271849/#271851.*
