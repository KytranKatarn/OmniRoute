# Warmboot Residency Profiles — design

**Date**: 2026-08-31 · **Owner decision**: Kytran · **Tasks**: #6215 (supersedes #6214), #6214
**Status**: DESIGN — nothing built yet

---

## 1. The problem, measured

Cold residency costs **45×**. Measured live this session, same capability, same node,
same prompt shape (`scripts/wtf_model_ab.py`):

```
geo, qwen2.5:1.5b, COLD first call ....  352.2s
geo, qwen2.5:1.5b, warm ...............    7.5s / 7.8s
```

That dwarfs every other lever available. For comparison, the *model-choice* difference on
the same task was under 2× — and even that ranking was the opposite of what the aggregate
logs implied.

### 1.1 The trap this design exists to close

`task_execution_log` grouped by `model_used` says `qwen2.5:7b` averages 89–151s and
`mistral:7b` averages 7s. That reading produced a recommendation to swap the WTF agents to
mistral. **It was wrong.** Measured directly on identical prompts:

| model | n | ok | median | max |
|---|---|---|---|---|
| `qwen2.5:7b` | 5 | 100% | **5.3s** | 9.2s |
| `mistral:7b` | 5 | 100% | 15.6s | 18.3s |
| `llama3.2:3b` | 5 | 100% | 28.0s | 37.5s |

`qwen2.5:7b` is 3× **faster**. The aggregate was measuring **cold loads, queue position and
`_WTF_CPU_FIRST`'s deliberate CPU routing** — and attributing all of it to the model.

> **Model-attributed latency is not model speed.** Any future tuning must measure the model
> directly, warm, on identical prompts, reporting **medians** and discarding the first call
> per model as a cold load.

### 1.2 Why it matters commercially

WTF is **59.5%** of all fleet dispatch (43,378 of 72,917 runs / 7d) against a 54,346-article
backlog draining at ~10/hr net. The backlog is not clearing because per-item cost is
dominated by residency misses, not by model capability.

---

## 2. What ALREADY exists — do not rebuild any of this

Three independent layers already implement pieces of warm planning. The gap is that
**nothing connects them to a workload.**

| layer | where | granularity | nature |
|---|---|---|---|
| **A.R.M.A.D.A. warm-set provisioner** | `fleet_node_routes.api_provision_warm_set`, `POST /api/nodes/<id>/provision-warm-set`; `services/node_provisioning.recommend()` | per **NODE** | hardware-derived (VRAM/RAM tiers) |
| **Dispatcher node affinity** | `department_dispatcher.CAPABILITY_NODE_AFFINITY` (~L440) | per **CAPABILITY** | hand-tuned constants |
| **Keep-alive pings** | `services/fleet_jobs.warmup_fleet_models()` (20 min) | per **CAPABILITY** | resets Ollama `KEEP_ALIVE` |
| **Reactive load** | `orchestration_engine._step_gpu_check` → `loaded_model` / `can_use_loaded` / `swap_required`; `model_service.ensure_model_ready()` | per **DISPATCH** | on-demand, after the fact |
| **State of record** | `model_load_state` table; `_restore_model_state()` on node online | per **HOST** | persistence only |

### 2.1 `CAPABILITY_NODE_AFFINITY` is already a residency planner in disguise

Its 70 lines of comments are almost entirely warm-eviction reasoning:

- *"stays OFF the Defiant GPU so it can't evict the warm review 7B (#1905)"*
- *"8GB is reserved for the warm review 7B"*
- *"gemma3 6.3GB + 7B ~5GB cannot coexist on 8GB → F.O.R.G.E. reviews cold-loaded"*
- *"mistral:7b stays warm; translate is latency-tolerant"*

But it expresses **where work is ROUTED**, never **what stays RESIDENT**. Those are different
statements, and the difference is the whole design.

### 2.2 It provably drifts

The file admits it (L433): the Defiant was *"preferred-first for NINE capabilities since the
08-21 rebalance **eroded** its #1905 warm-review protection"*. A `max_concurrent` change made
elsewhere silently broke an invariant that existed **only as a comment**. Nothing failed;
nothing alarmed; review success fell to 82%/57%.

> **Any design that leaves residency invariants in comments will drift again.** The invariant
> must be declared as data and checked by something that can fail.

---

## 3. Design

### 3.1 A residency profile

A **profile** declares what should be RESIDENT, per node, per tier, for a named workload —
independent of routing.

```
profile: news
  starbase:   { gpu: [qwen2.5:7b], cpu_ram: [gemma3:12b] }
  runabout:   { gpu: [qwen2.5:1.5b], cpu_ram: [llama3.2:3b] }
  defiant:    { gpu: [], reserved_vram_gb: 8.0, reserved_for: code_review }   # #1905
  citadel:    { cpu_ram: [qwen2.5:7b] }                                       # _WTF_CPU_FIRST
```

Three tiers, matching what Starbase and the Starships actually offer:

| tier | meaning | sizing input |
|---|---|---|
| `gpu` | fully GPU-resident | `remote_nodes.gpu_vram_gb` = **largest single card**, never the sum |
| `span` | deliberately split across cards | hub only; Ollama does this routinely (`GPULayers:49[Quadro 31, TITAN 18]`) |
| `cpu_ram` | CPU-resident by design | `ram_gb` minus host headroom |

⚠️ **A spanning model consumes headroom on BOTH cards simultaneously**, which current
placement does not anticipate — this is how hub VRAM budget hit 0.0 GB on 2026-08-15 and
pushed `qwen2.5:7b` to CPU. A profile that declares `span` must reserve on both.

### 3.2 Storage — data, not constants

`platform_settings` key `fleet:residency:profiles` (JSON), read through a TTL-cached
resolver in the shape of `services/signal_accounts.py`:

- editable without deploy (the `ship_classes` precedent)
- a hardcoded fallback identical to today's `CAPABILITY_NODE_AFFINITY`-implied set, so an
  absent/corrupt key is **byte-identical to current behaviour**
- one canonicalisation point for node identity — `node_id` (varchar), **never** the int `id`
  (the recurring fleet trap)

### 3.3 Activation

A profile is **requested**, not switched globally:

```
POST /tools/department-hq/api/fleet/residency/activate  {profile: "news", ttl_minutes: 90}
GET  /tools/department-hq/api/fleet/residency/status
```

Activation does **not** evict anything. It enqueues warm-up work through the existing
`dispatch()` path (ADR-013 — never a direct Ollama call) and lets `KEEP_ALIVE=60m` hold it.
Eviction stays Ollama's business; we only influence what is *asked for*.

`ttl_minutes` matters: a profile that never expires is a permanent reservation, which is how
one workload starves the others.

### 3.4 Who calls it

- **Backlog drains** (`*_backlog` producers in `ingest/`) activate `news` before draining and
  let it lapse. This is the single highest-value caller — it converts the 45× cold penalty
  into a one-time cost amortised over thousands of items.
- **A.R.M.A.D.A. Fleet tab** gets a manual selector — the operator surface Kytran asked for.
- **`warmup_fleet_models()`** takes the active profile as its source list instead of its
  current fixed capability tuple.

### 3.5 The drift guard — the part that must not be skipped

A scheduled check that **fails loudly** when declared residency and reality diverge:

```
services/residency_monitor.check_residency()
  declared (profile) vs actual (model_load_state + node heartbeat ollama_models)
  -> alert on: a reserved tier occupied by a foreign model  (the #1905 erosion)
               a declared-resident model absent > N cycles  (silent eviction)
               a node whose max_concurrent/max_model_gb makes its profile unsatisfiable
```

That third check is the one that would have caught the 08-21 rebalance: it ties the
*capacity* knobs to the *residency* intent, which nothing does today.

---

## 4. What this deliberately does NOT do

- **Does not change model selection.** #6215 established the current models are fine; the
  problem was never model choice.
- **Does not replace `CAPABILITY_NODE_AFFINITY`.** Routing and residency are complementary:
  affinity says where work goes, profiles say what is warm when it arrives. Collapsing them
  would lose the carefully-earned routing knowledge in those comments.
- **Does not pin or reserve GPU memory directly.** We influence what is requested; Ollama
  owns eviction. Fighting it is how you get thrash.
- **Does not touch `agents.model`.** Per-agent model choice stays an owner decision.

---

## 5. Sequence

1. **Observer first** — `check_residency()` + the status endpoint, reporting only. Run it for
   a week against today's implicit profile. If it cannot describe current reality accurately,
   the model is wrong and nothing further should be built. *(feedback_ship-the-observer-first)*
2. Profile storage + resolver + hardcoded fallback. No behaviour change.
3. `activate()` wired to ONE caller — the WTF backlog drain — with a measured before/after on
   drain rate. State the prediction in advance.
4. A.R.M.A.D.A. Fleet tab selector.
5. `warmup_fleet_models()` reads the active profile.

Each step is independently revertible. Step 1 ships no behaviour at all.

---

## 6. Acceptance

Not "the code exists" but: **the WTF backlog net drain rate rises measurably after a `news`
activation, and the residency monitor reports zero unsatisfiable profiles.** Baseline to beat,
captured 2026-08-31: pending **54,346**, intake ~24/hr, net drain ~10/hr, WTF = **59.5%** of
fleet dispatch.
