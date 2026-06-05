# KSO as Mesh Control Plane + DR-Scope Expansion — Vision & Next-Session Targets
*Created 2026-06-02. Grew out of the hub-failure DR work (Project #368). Companion: `.claude/plans/dr-plan-boston2.md`, KB #270237 (DRP-mode state + distribution direction), #270232 (5b/backup/scheduler).*

## The idea (owner, 2026-06-02)
Evolve the platform from "one hub runs everything" to a **control-plane / data-plane split**, with **KSO as the fleet control plane**. DR stops being a per-service script and becomes a *property of the control plane* ("a node died → reschedule its dockers onto a healthy node").

### Layering
- **Layer 0 — KSO control plane (mesh-native):** Docker lifecycle (KSO already has a Docker tab — deploy/load/restart), monitoring, compliance, host management, **and backup orchestration**, across *every* node. Agent per node + a **portable control plane** that runs anywhere (incl. boston-2).
- **Layer 1 — products as managed dockers:** ARCHIE, KBS, CREED, Watch, WTF become workloads KSO deploys + watches, not hand-tended services.
- **Layer 2 — marketplace + micro-transactions (FUTURE / parked):** deploy and eventually *sell* services from the control plane — a self-hosted "app store over the mesh" with a micro-transaction billing rail. Real product upside; keep it OUT of the infra work for now.

### THE hard constraint (design this first)
**If KSO manages everything, KSO becomes the new single point of failure** unless the control plane is itself HA / multi-node with no single home. *The thing that manages resilience must be the most resilient thing.* KSO-mesh must be multi-node (quorum / portable control plane) from day one — otherwise we've just relocated the `.200` problem.

### Backup — move it out of the platform (conductor / executor split)
Backup is an **infra concern, not an ARCHIE feature.** Move *orchestration* to KSO (schedule, track, verify, GFS retention, ship-to-DR, one pane of backup health across the fleet); keep *execution* where the data lives (the DB/host runs its own `pg_dump`/volume snapshot). Avoids deep DB coupling in KSO while centralizing visibility + control.

## Standalone DR maturity (NOT all equal)
| Service | Maturity | DR action |
|---|---|---|
| ARCHIE platform + brain | ✅ refined, in DR (5b proven) | done; expand via control plane |
| Watch products + WTF | ✅ refined, running (own VPS) | survive already; WTF needs DB-repoint handling |
| **C.R.E.E.D.** | ✅ refined, running | bring into DR — replicate own DB + stage on boston-2 (proven pattern) |
| **KSO** | ✅ refined, running | promote to mesh control plane (the Layer-0 work) |
| Stalwart Mail | ✅ running | secondary-MX (spool inbound) tier 1; full standby tier 2 |
| **KBS** | 🔧 **NOT done — DATA exists, UI + backend still need review/design/code** | **DEV TRACK, not a DR-placement decision yet.** Refine + build first; DR-place once it's actually built. Revenue product (24 plugins, Stripe, paywall, customer+payment data) → highest value, most care. |
| Media Hub | family/personal | **OUT of DR scope** (not a Kytran Empowerment Inc. concern) |

## DESIGN DECISIONS — 2026-06-04 (#3688 spike)

**Q1: Evolve KSO vs new orchestrator?**
→ **EVOLVE KSO.** KSO already ships `docker_routes.py`, `hub_client.py`, compliance, monitoring, firewall. No new deployment friction. Identity pivot: KSO becomes "fleet control plane" which fits — it was always about server management. New project owns the Phase 1 build.

**Q2: Multi-node HA for control plane?**
→ **2-node primary/secondary, watchdog-promoted** — same pattern as `archie_scheduler_standby`. Run KSO on hub (primary) and boston-2 (secondary). State: PostgreSQL (already replicated) + git-versioned config. Leader election: watchdog on boston-2 promotes KSO-standby when hub is down (same trigger as `failover.sh`). No raft needed at this scale.

**Q3: Own project or stay under #368?**
→ **Own project.** #368 is complete and closed. Control plane is broader — DR is just the first use case. New project = "KSO Mesh Control Plane — Phase 1".

**Boundary with DHQ (critical — user confirmed "DHQ is part of platform"):**
- KSO owns: Docker container lifecycle across nodes, host compliance, backup orchestration, host monitoring
- DHQ owns: inference dispatch, agent lifecycle, model loading, fleet resource routing
- The two systems communicate via the mesh but do NOT overlap. KSO is infra; DHQ is AI.

**Phase 1 scope (build order):**
1. Cross-node Docker visibility — KSO hub lists containers across all mesh nodes via KSO agents (extend `hub_client.py`)
2. KSO on boston-2 as standby control plane — `failover.sh` promotes it the same as `archie_scheduler_standby`
3. Remote Docker operations — restart/stop a container on any node from KSO hub UI
4. Backup conductor — GFS schedule + job tracking + alerting in KSO; execution stays on data host via SSH

**Phase 2 (after Phase 1 proven):**
- Auto-reschedule: on node loss, hub KSO moves movable containers to healthy nodes
- Backup executor migration: replace platform backup_manager scheduling with KSO conductor

**Phase 3 (future):**
- Marketplace + micro-transactions (Layer-2, still parked)

## NEXT-SESSION TARGET GOALS (priority order)
1. **Phase 7 — auto-promote watchdog** (highest leverage). Today everything waits on a human running `failover.sh`. A watchdog on boston-2 + surviving-node quorum that auto-promotes on confirmed hub loss (no false-positive on a blip). This makes every other DR investment actually fire by itself.
2. **C.R.E.E.D. into DR.** Replicate its DB + stage image on boston-2, start via `failover.sh`. Public scores API is the external surface (creed-ai.org + WTF depend on it).
3. **Mail secondary-MX.** Cheap, high-value: an outpost MX that spools inbound during an outage so no incoming mail is lost. (Full send/receive standby = later.)
4. **KSO mesh control-plane DESIGN SPIKE.** Design the multi-node control plane (HA constraint above), the Docker tab as the deploy primitive, and the backup-orchestration move. Design before build.
5. **KBS DEV TRACK (separate from DR).** Review → design → build the UI + backend on top of the existing data. Own scoping; not blocked on DR.
6. **Marketplace + micro-transactions** — Layer-2, parked until the control plane is solid.

## Open design questions (decide next session)
- KSO control plane: **evolve the existing KSO standalone** vs **new "fleet orchestrator" capability**?
- Marketplace + micro-tx: park as future vs scope now? (Leaning: park.)
- Does the control-plane vision get its **own project**, or stay under #368? (Leaning: new project — #368 is specifically the boston-2 warm standby; the control plane is broader.)

## Sequencing note
The near-term DR fixes (1–3) ARE the first bricks of the control plane — don't treat vision vs. fixes as a choice. Keep KBS (5) and marketplace (6) as separate tracks so they don't entangle the infra resilience work.
