# Verifier Batch 1 — 4 high-leverage findings (2026-06-08)

Independent adversarial re-checks (one agent per claim) against live code + DB.

## V1 — kin_warmth keeper "~50% broken" → **PARTIALLY CONFIRMED, severity LOW** (downgraded)
- Stats EXACT: 6h = **33 done / 20 expired / 10 failed (49% miss)**; all 20 expired had `claimed_at IS NULL`. ✅ (`fleet_jobs.py:319`, INSERT :460-469, `expires_at=NOW()+5min`, `IntervalTrigger(minutes=20)` :1104).
- **Claim's CAUSE was WRONG:** `_claim_preferred_node_tasks` defaults `limit=2` but the sole caller passes **`limit=4`** (`model_dispatch_service.py:1276`) — not the binding constraint. Priority is escalated 1→9 by a trigger (not stuck at floor).
- Real cause: 5-min TTL racing `MAX_TASKS_PER_CYCLE` gating (warmth drains only after the main parallel drain) + rest-window/offline.
- **Impact LOW:** these are no-op pilot-light `ping` warmers; expiry self-heals next cycle → wasteful telemetry noise, not an outage. (Still worth fixing as part of the warm-fleet, but not critical.)

## V2 — queue-drain path never writes task_execution_log → **CONFIRMED, HIGH**
- `model_dispatch_service.py`: **zero** `INSERT INTO task_execution_log`, **zero** `_log_execution` calls. `_execute_task` → `_dispatch_to_node`/`_execute_llm` → `_mark_done` writes only `result_tokens` (:480).
- `_log_execution` (`department_dispatcher.py:3746`, INSERT :3822) — all 11 call sites inside `request_work` (:5507–7666); queue worker bypasses `request_work`.
- Token Economy (`code_health_routes.py:320/352/387/411`) + ARMADA (`dispatch_routes.py:472/1030`) read **TEL only** (a prior `dispatch_pending_queue` join was REMOVED, :1098-1100).
- LIVE: TEL `module_source ILIKE '%model_dispatch%'` = **0**; `dispatch_pending_queue` done/24h = **1382 rows / 209,312 tokens**.
- **NOT a regression** — predates #1516/#1517/#1518 (originates #452/#806; #1390 added `result_tokens` capture but no TEL write). ✅
- ⇒ ~209k tokens/day + ~1382 dispatches/day **invisible in Token Economy + ARMADA**. Tokens persisted in `result_tokens`, just unread.

## V3 — preferred-node path bypasses the capacity gate → **CONFIRMED, HIGH**
- `_claim_preferred_node_tasks` docstring (`model_dispatch_service.py:442`): *"These tasks bypass the warm-model filter — the node will cold-load the model if needed."* No fit check.
- `_execute_task` preferred branch (:801-819) validates ONLY online+heartbeat; **no** `can_node_run_model`. Contrast :139-150 (general path DOES gate).
- `department_dispatcher.py:8774` `if not target_host:  # budget enforcer only manages the hub` → remote node skips capacity entirely (confirms #1517 hub-only `ensure_capacity`).
- **Impact:** a 7B pinned to a CPU node is warm-booted there → disk-swap → timeout → `_requeue_cold` loops. Exactly what the manual Citadel benchmark dispatches did.
- **Fix:** in `_execute_task` preferred branch (after node_row resolve), `if not can_node_run_model(node_row, model): drop pin → hub/fail`. Mirror the :139-150 fail-open gate.

## V4 — fit gate vs scorer disagree on CPU-7B → **CONFIRMED, MEDIUM**
- Computed (qwen2.5:7b on Citadel CPU 31GB, cap=9): `fit=True, score=None` at load=22/hb=None AND at load=0/hb=None AND load=22/hb=fresh. Only `load=0 + hb=fresh` → both admit (score=0.80). cap=4 → both reject. Divergence is real.
- Root cause: `score_node_for_model` returns `None` when `score<=0`, **conflating CAPACITY with RANKING** (load/heartbeat/tier penalties drag it negative). `can_node_run_model` (async, `model_dispatch_service.py:141`) ignores those; sync path (`fleet_resource_router.py:292` via `find_best_node_for_model`, called `department_dispatcher.py:709/727`) uses score → opposite admission.
- **Fix:** in `find_best_node_for_model`, gate admission on `can_node_run_model`, use `score` only to RANK (floor None→0.001). One admission predicate across both paths.

---
**Batch-1 net:** 3 CONFIRMED (V2/V3 HIGH, V4 MEDIUM), 1 downgraded (V1 LOW). The headline real issues stand: **queue→TEL tracking gap** + **preferred-node bypass** + **fit/scorer divergence**. The kin_warmth keeper is real but lower-impact than audited.
