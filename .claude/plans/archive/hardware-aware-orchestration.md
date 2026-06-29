# Hardware-Aware LLM Orchestration — the "full circle" (design)

**Owner vision (2026-06-03, project #371):** KSO on Starbase already pulls *deep* hardware
(RAM type/speed, drive type/speed, SMART, etc.). Bring that depth to **every node**, then
**record which LLM runs best on which hardware**, keep it **historical**, and feed it back so
the **router (#2516)**, **Academy Bay** (agent proficiency), and **K.I.N.** (assignment +
scheduling + welfare) all make hardware-aware decisions. "Full circle of hardware → agent
proficiency."

Why it matters: RAM speed (DDR4-2400 vs DDR5-6000) and drive speed (HDD vs SATA-SSD vs NVMe)
materially change **model cold-load time** and **throughput** — so the *same* model is a great
fit on one node and a poor one on another. Today we route on RAM/VRAM size only; we're blind to
*speed*.

---

## Feasibility — YES. KSO already proves the mechanism.

KSO's `host_monitor.py` / `system_service.py` collect hardware with plain shell probes:
`/proc/meminfo`, `lsblk`, `smartctl` (+ `get_smart_details()`), and `dmidecode` for memory.
The node sync agent (`node_client/node_sync.py`) already runs on every node with the access to
do the same — we just extend the heartbeat. **Phase 0 is already shipped:** PR #1419 added
`cpu_cores` + `cpu_model` to the heartbeat (the first deep-hardware fields).

Cross-platform collectors (the only real complexity):
| Field | Linux outposts (root) | Windows Starships (Docker Desktop) |
|-------|----------------------|------------------------------------|
| RAM type/speed | `dmidecode -t memory` (DDR4/DDR5, MHz, manufacturer) | WMI `Win32_PhysicalMemory` (Speed, SMBIOSMemoryType, Manufacturer) |
| Drive type | `lsblk -d -o NAME,ROTA,TRAN` (rota=0→SSD, tran=nvme) | WMI `Win32_DiskDrive` / `MSFT_PhysicalDisk` (MediaType, BusType) |
| Drive speed/health | `smartctl -i/-A`, `hdparm -t` | WMI / `Get-PhysicalDisk` |
| CPU detail | `lscpu` (flags, MHz, cache) | WMI `Win32_Processor` |
Note: `dmidecode`/`smartctl` need root/`--privileged` or host probing — Linux outposts run the
sync agent as root; Windows uses WMI via the node's PowerShell, no privilege issue.

---

## Phases

**Phase 0 — DONE (PR #1419):** `cpu_cores` + `cpu_model` in heartbeat → `remote_nodes`. Surfaced
in the ARMADA node-detail panel (PR #1421).

**Phase 1 — Deep hardware inventory.** Extend the heartbeat with a `hardware` block:
`{ram:[{type,speed_mhz,size_gb,manufacturer}], disks:[{name,media_type,bus,size_gb,health}],
cpu:{flags,base_mhz,cache}}`. Node-side cross-platform collectors (table above), cached (hardware
is static — collect once/hour, not every 30s). Store in `remote_nodes.extra_capabilities.hardware`
(JSONB). Surface in the node-detail panel. Mirrors KSO depth. *(feeds #2516)*

**Phase 2 — LLM performance recording.** On every fleet dispatch, capture
`(model, node, cold_load_ms, ttft_ms, tokens_per_sec, prompt_tok, gen_tok)` into a new
`node_model_perf` table (the node already times pulls/loads; the dispatcher already logs to
`task_execution_log` — extend it). This is the historical record. *(this IS #825)*

**Phase 3 — Optimal-combination table.** Aggregate Phase 2 × Phase 1 → `node_model_fit`:
per (model, node) a score from load-time + throughput + welfare headroom. "Best node for model X",
"best model for node Y". The router (#2516) reads this instead of guessing from size. The
provisioning wizard (#3731) uses it to recommend the *fastest-loading* warm set per node, not just
*fitting* ones.

**Phase 4 — Full circle: Academy + K.I.N.**
- **Academy Bay:** agent proficiency/training placement reads `node_model_fit` — train/benchmark an
  agent on the hardware that runs its model best; proficiency scores account for the hardware they
  ran on.
- **K.I.N.:** historical perf + hardware → smarter **assignment** (put the 7B agent on the NVMe/DDR5
  node, the 1.5B on the slow node) and **scheduling** (pre-warm the right model on the right node
  ahead of a known workload; welfare-gate using real throughput headroom, not guesses).

---

## Schema sketch (new)
- `remote_nodes.extra_capabilities.hardware` (JSONB) — Phase 1 inventory.
- `node_model_perf(node_id, model, cold_load_ms, ttft_ms, tok_per_sec, measured_at)` — Phase 2 log.
- `node_model_fit(node_id, model, fit_score, sample_count, updated_at)` — Phase 3 rollup (job-built).

## Maps to existing tasks
#2516 resource-inventory→routing (Phase 1+3) · #825 perf benchmarking (Phase 2) · #3688 KSO control
plane (KSO is the natural collector/owner) · Academy Bay + K.I.N. (Phase 4). This design unifies
them under one data spine: **inventory → perf → fit → orchestration.**

## Phase 5 — C.R.E.E.D. governance overlay (interconnect)
The fit/perf/hardware spine gives C.R.E.E.D. (E.T.H.O.S.) concrete signals it lacks today:
- **Fairness/welfare:** placing an agent on hardware that cold-loads its model slowly = real
  latency/timeout "stress." C.R.E.E.D. can flag/forbid placements that degrade an agent's
  welfare vs an available better-fit node — welfare gating becomes hardware-aware, not guessed.
- **Resource stewardship / sustainability:** optimal combos = less wasted compute + energy
  (no cold-loading a 7B on a slow HDD node). A new governance dimension ("efficiency/stewardship")
  scored from `node_model_fit` waste vs optimum.
- **Explainable decisions:** routing/placement choices become auditable ("ran on node Y because
  fit_score 0.9, load 4s") — C.R.E.E.D.'s transparency surface gains a concrete, defensible record.
- **Public posture:** resource-efficiency can become a published governance metric on the C.R.E.E.D.
  scorecard (like the compliance badges). Review whether it helps before wiring — opt-in.

So the full circle is: **inventory → perf → fit → (router #2516 · Academy · K.I.N.) → C.R.E.E.D.
governs the loop.**

## Build order recommendation
Phase 1 first (cheap, extends shipped Phase 0, immediately enriches the ARMADA panel + wizard).
Then Phase 2 (start recording now so history accrues while Phase 3/4 are built). Phase 3/4 need
Phase 2 history to be meaningful — so begin recording early even if the rollup/consumers come later.
