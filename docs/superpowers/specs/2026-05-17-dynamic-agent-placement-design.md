# Dynamic Agent Placement — Hub ↔ Node ↔ VPS Float Orchestration

**Date:** 2026-05-17
**Status:** Design (no code tonight; ship next session)
**Trigger:** Kytran's articulation of the multi-cluster orchestration vision — agents should float to wherever resources are free, not pin to one node.

## The vision in one paragraph

The cluster is a single resource pool, not a hierarchy. When V.E.R.I.F.Y. (or any agent) has work to dispatch, the system should pick the best AVAILABLE node at that moment — hub, Starship-246, Starship-245, or outpost-us — based on model fit, GPU availability, and current load. The agent isn't pinned to a home; it floats. If hub goes down, agents that can run on nodes keep working. If a Starship is idle while hub is busy, the next dispatch flows to the Starship. ComfyUI gets the same treatment, except its multi-minute task lock prevents mid-task migration. **The hardware decides where work happens, not the org chart.**

## Current state vs. target state

```
TODAY (sticky-pin model):
  agents.current_node_id = <one node>      ← pinned at creation
  dispatcher logs "Node-preference: AGENT@<pinned_node>"  ← honored before fleet routing
  fleet_resource_router score is computed BUT often not consulted
  Result: 1 agent → 1 node, hardware sits idle, no float

TARGET (dynamic placement model):
  agents.current_node_id = NULL OR soft "home" hint
  At dispatch time:
    1. Resolve capability → agent (existing skill-first routing)
    2. Compute fleet_resource_router scores for ALL nodes with the model loaded
    3. Filter out nodes at welfare cap (per-node concurrent task limit)
    4. Pick highest-scoring AVAILABLE node
    5. Lock that node's slot for the duration of the task
    6. Release lock on completion — next dispatch decides fresh
  Result: 1 agent floats across cluster, hardware fully utilized
```

## What's already shipped (the plumbing layer)

| Layer | Status | Where |
|---|---|---|
| Fleet heartbeat → model registry | ✅ PR #780 | `fleet_node_routes.py:1328` RealDictRow fix |
| Per-model node scoring | ✅ PR #782 | `fleet_resource_router.py` (small CPU prefers CPU node bonus) |
| Per-model VRAM-aware ComfyUI routing | ✅ existing | `comfyui_manager.get_best_comfyui_url(model_name)` |
| ComfyUI atomic claim + VRAM swap | ✅ existing | `agent_loop.py:1648` FOR UPDATE SKIP LOCKED + `_vram_swap_for_comfyui(node_db_id)` |
| ComfyUI parallel claim (3-per-cycle) | ✅ PR #783 | `agent_loop.py` LIMIT 1→3 |
| FLEET_RESOURCE_ROUTING_ENABLED flag | ✅ activated tonight | env in both `.env` files |

**The pieces exist.** What's missing is removing the agent→node pin so the scorer actually gets used.

## What needs to ship (3 code touch points)

### 1. Dispatcher: convert "Node-preference" from hard pin to soft hint

Today in `department_dispatcher.py`:
```
INFO [BridgeDispatcher] Node-preference: V.E.R.I.F.Y.@outpost-us for 'fact_check' (agent 116 stationed on fleet)
INFO [BridgeDispatcher] Fleet dispatch → outpost-us  ← pin honored, scoring skipped
```

Change to:
```python
# Pseudo-code for the change
preferred_node = agent.current_node_id          # soft hint (homing)
candidates = fleet_router.candidates_for(model=agent.model)  # all nodes with model loaded
candidates = welfare.filter_at_cap(candidates, agent_id=agent.id)   # respect per-node budget
if not candidates:
    return escalate_to_cloud_or_fail
best = max(candidates, key=lambda n: fleet_router.score(n, agent.model, prefer=preferred_node))
dispatch_to(best)
```

The `prefer=preferred_node` adds a small (+0.3?) bonus to the home node so all-else-equal it wins, but a busy home loses to an idle peer. **That's the float.**

### 2. Welfare: per-node concurrent task limit

`agent_budgets.current_task_count` today is per-agent global. For float to work without overloading any single node:
- New table or JSONB column: `agent_node_load(agent_id, node_id, in_flight_count, last_updated)`
- Welfare check `filter_at_cap` queries this and rejects nodes where an agent already has N in-flight tasks (configurable, default 1 for GPU-bound tasks, 3 for CPU-bound)

This is what prevents 5 V.E.R.I.F.Y. dispatches all stacking on Starship-246 while .245 sits idle.

### 3. ComfyUI: same float pattern, lock-aware

ComfyUI tasks are GPU-bound for minutes. Float placement applies the same way, with these extras (most already in place):
- `media_generation_queue` row lock holds for the entire job → no agent migration mid-task ✅ (already)
- New ComfyUI dispatch picks the BEST AVAILABLE ComfyUI backend (per `get_best_comfyui_url`) ✅ (already)
- VRAM swap is per-node-aware (`_vram_swap_for_comfyui(node_db_id)`) ✅ (already)
- **Only addition needed**: `comfyui_manager` should consult fleet router's "is this node currently running ComfyUI?" before dispatching a second job to the same node. Today multiple jobs CAN stack on hub if .246/.245 unavailable; with float, they should prefer the idle node.

So ComfyUI is ~95% there. The remaining 5% is a "is busy?" probe.

## ComfyUI guarantees during float (Kytran's concern)

The user asked: when ComfyUI is running, don't yank the agent mid-task.

**Already guaranteed by**:
1. `media_generation_queue.status='generating'` row stays locked via FOR UPDATE → no other worker can touch
2. `_vram_swap_for_comfyui` is called BEFORE generate_image, restored AFTER — atomic from the agent's perspective
3. New dispatches for OTHER agents/models route to DIFFERENT nodes (fleet routing) — they don't disturb the in-flight ComfyUI job

What this design does NOT do (intentional):
- Does not preempt running ComfyUI to migrate an agent to a faster node
- Does not interrupt mid-inference even if a more powerful node frees up
- Tasks are sticky to their start node until completion

## Hub ↔ Node bidirectional float

Both directions are natural consequences of the float logic:

**Hub → Node (offload):**
- Agent stationed at hub gets a dispatch
- Hub is busy with SDXL (Quadro saturated)
- Fleet router scores: Starship-246 +1.0 (model loaded, GPU free), hub +0.3 (busy)
- Dispatch goes to .246
- Hub's GPU stays free for the SDXL it's running

**Node → Hub (escalation):**
- Agent stationed at outpost gets a 7B GPU dispatch
- Outpost is CPU-only, would be slow
- Fleet router scores: hub +1.0 (model loaded, GPU available), .246 +1.0 (model loaded, idle), outpost -0.3
- Dispatch goes to whichever GPU node is idler
- Outpost stays handling small CPU work

## VPS independence (when hub is down)

The float logic assumes hub is the dispatcher. If hub is down:
- VPS workers fail because they POST to `100.64.0.4:3000`
- This is the "Option A" we deferred — VPS-side `ai_dispatcher.analyze()` falls back to LOCAL outpost Ollama for small-model tasks when hub returns 5xx/timeout
- News team keeps doing basic analysis (bias, summary, geo) on outpost until hub returns
- Deep_analysis (LLM-heavy) pauses until hub is back

**Open question for next session**: should the float logic include "if hub down, run a mini-dispatcher locally on outpost"? That's bigger scope — defer until Option A ships.

## Build order (next session)

1. **Add per-node welfare table** — `agent_node_load(agent_id, node_id, in_flight, updated_at)`. Migration only, no behavior change.
2. **Update dispatcher** — convert station pin to soft hint, consult fleet router for all candidates.
3. **Wire welfare filter** — `filter_at_cap()` rejects over-capacity nodes per agent.
4. **Smoke test one capability** — `deep_analysis` with V.E.R.I.F.Y. should now route per-dispatch (outpost / .245 / .246 / hub based on load).
5. **Expand to all capabilities** — once one works, the rest follow the same pattern.
6. **(Then) Option A** — VPS fallback for hub-down resilience.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Agent welfare misaccounted across nodes | New `agent_node_load` table is authoritative; existing `agent_budgets` becomes derived (sum across nodes) |
| Node selection latency added to every dispatch | Cache fleet scores for 30s (heartbeat cadence anyway) |
| Hot node thrashing (every dispatch picks same fastest node) | Welfare cap + load score penalty already prevent this |
| ComfyUI long-task agent appears "absent" | media_generation_queue row IS the canonical state; agent welfare just reflects in_flight |
| Hub goes down — float logic itself can't run | Acknowledged; addressed by Option A in a future PR |
| Agents pinned by humans for specific reasons | Keep `current_node_id` as soft hint (+bonus when chosen); allows operator override without re-pinning |

## What this design does NOT cover (out of scope)

- Cross-node ComfyUI batching (sending a multi-image batch to multiple nodes)
- GPU-aware preemption (we explicitly do NOT preempt mid-task)
- Live agent migration mid-task (sticky to start node)
- Custom routing rules per-customer / per-tier (future)
- Federated learning across nodes (different problem entirely)

## Touch summary (preview of next-session PR scope)

| File | Change | Lines |
|---|---|---|
| `database/migrations/00X_agent_node_load.sql` | NEW table | ~20 |
| `services/welfare_service.py` (or similar) | Add `filter_at_cap()` + `record_dispatch_start/end()` | ~40 |
| `tools/department_hq/services/department_dispatcher.py` | Replace station-pin block with fleet-router selection | ~30 changed |
| `tools/department_hq/services/department_coordinator.py` | Pass `agent.current_node_id` as soft hint not hard pin | ~5 |
| Tests | Cover: hub-busy-routes-to-Starship, all-Starships-busy-falls-back-to-outpost, etc. | ~60 |

Total: ~155 lines across 5 files. Single focused PR.
