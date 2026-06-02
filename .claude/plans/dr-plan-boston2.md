# A.R.C.H.I.E. HA / Disaster-Recovery — Master Phased Plan
*Goal: an always-on warm standby so that when the Starbase (hub) is UP we run at full power, and when it's DOWN the platform + cluster keep running (limited) on a backup node — then fail back to full power.*
*Owner: Kytran. Created 2026-06-01. Companions: `.claude/hub-spof-dependency-audit.md`, `.claude/plans/hub-ha-phased-plan.md`, `.claude/plans/auth-resilience-scope.md`.*

---

## The DR node — outpost-boston-2 (CHOSEN, KVM8 confirmed)
| Attribute | Value |
|---|---|
| Public IP / Mesh IP | `2.25.133.122` / `100.64.0.10` |
| Plan | **KVM 8 — 8 vCPU / 32 GB / 400 GB** (Hostinger DC24, US-East) |
| Login | `root@` + `~/.ssh/id_ed25519` (NOT kytran@) |
| Today | node-agent only (`archie_outpost_sync`+`archie_node_api`) — spare capacity |

US-East = ~10–30 ms to the Montreal hub (low replication lag) and geographically separate (survives a hub *site* outage). **No GPU** → during DR, big-model/ComfyUI inference is cloud/CPU-fallback; core platform runs fine.

## Operating modes — always-on warm standby
| State | Hub (Montreal) | boston-2 | Result |
|---|---|---|---|
| **NORMAL** (hub up) | PRIMARY — full GPU/128 GB, all platform/dispatch/ComfyUI | live streaming **replica** + warm standby (idle); optional read-offload | **FULL POWER** |
| **DR** (hub down) | dead / fenced | promote → run platform + cluster (limited) | **STAYS UP** |
| **FAILBACK** (hub back) | rebuilt as replica → resume primary | demote to replica | **back to FULL POWER** |
**Invariant:** exactly ONE primary takes writes (split-brain guard). Async streaming → boston-2 always seconds-fresh, hub never throttled.

## Surviving compute when hub is down (what "limited" means)
| Failure | Survives | Inference |
|---|---|---|
| **Hub box only** (Montreal LAN/net up) | boston-2 + Starships 245/246 (GPU 7B) + 5 CPU outposts | 7B GPU + small CPU + cloud (only M4000-large + ComfyUI lost) |
| **Whole Montreal site** (power/ISP) | boston-2 + 4 global CPU outposts | small CPU + cloud only |
Either way boston-2 runs the dispatcher and reaches survivors **directly over the mesh** (Headscale data plane is peer-to-peer — established tunnels persist without the hub coordinator). **Limited resources, full cluster access to whatever survived.**

## Targets
- **RPO** (data loss): seconds (streaming replication).
- **RTO** (downtime): warm standby ≈ **minutes** (promote → start → DNS); automated later.

## Scope
- **In:** `archie_database` (KB/auth/dispatch), `archie_platform`, `archie_scheduler`, mesh, ingress.
- **Degraded in DR:** GPU inference (cloud/CPU fallback), ComfyUI (off).
- **Already independent:** the 4 Watch products + WTF (local data + Phase 1 auth resilience) survive on their own.
- **Later:** hub-co-located standalones (KBS/CREED/KSO/Media Hub), media stack.

---

# PHASES (build in order)

## ✅ Phase 1 — Auth-outage resilience — DONE (2026-06-01)
All 4 Watch products survive a hub/IdP outage without logging users out. gov + civic fixed & verified (block-the-hub 2/2, unit 6/6, serving 200); legal + market already resilient by design. Branches committed (gov `b5f45c3`, civic `875ae54`) — ready for PRs. KB #270035 (pip-package gotcha).

## ✅ Phase 2 — Brain DB replica on boston-2 — DONE (2026-06-01)
LIVE: hub `archie_database` streams to read-only standby on boston-2 (`archie_dr_replica`, port 5433, pgvector/pgvector:pg16). Verified: state=streaming, lag=0, slot active, knowledge_base rows match (31201), in_recovery=t. Hub never restarted. Recipe + gotchas: KB #270036; script at boston-2:/opt/archie-dr/setup_replica.sh. **Read-survival achieved.** (Original plan below.)
- **Goal:** the brain DB exists in two places; read-survival immediately.
- **Steps:** install Postgres **16** on boston-2 (match hub major); `pg_basebackup` from hub `100.64.0.4:5432` → boston-2; enable **streaming replication** (`primary_conninfo` → `100.64.0.4`) for the `archie` cluster (DBs `archie`, `wtf`, `n8n`). UFW: mesh-only (`100.64.0.0/10` → 5432) both ends.
- **Verify:** `pg_stat_replication` on hub shows boston-2 streaming, lag < a few sec.
- **Risk:** low — read-only, no hub disruption (async). **Effort:** ~½ day.

## ✅ Phase 3 — Warm standby platform tier — DONE (2026-06-01, smoke-tested)
STAGED on boston-2: image `archie_brain-archie_platform` (docker save|load, 20.9 GB on disk, runs CPU-only), source `platform_v2/` + secrets + `.env` (same SECRET_KEY) under `/opt/archie-dr/platform/` (mounted as `/mnt/archie_brain`), compose `docker-compose.standby.yml` (DB→127.0.0.1:5433 local replica, no GPU, network_mode host). **Smoke test PASSED**: gunicorn booted, `GET /login → HTTP 200` against the read-only replica, then stopped (warm standby). Degraded-mode warnings expected/non-fatal: telegram_gateway module absent; email idle-worker can't resolve hub container DNS. Write-path validation deferred to the Phase 4 drill (needs promoted RW DB). (Original plan below.)
- **Goal:** boston-2 holds a ready-to-run platform pointed at its replica.
- **Steps:** stage `platform_v2` (or image) + compose + `.env` (`DB_HOST=localhost`, `BRIDGE_URL=http://100.64.0.10:3000`); stage **secrets** (encrypted). Keep cold (stopped) or warm (read-only).
- **Verify:** standby boots read-only against the replica, renders login/KB.
- **Risk:** low. **Effort:** ~1 day.

## ✅ Phase 4 — Self-sufficient failover — DONE + DRILLED (2026-06-02)
Staged off-hub on boston-2:/opt/archie-dr/: **failover.sh** (split-brain-guarded promote→start→verify) + **DR_RUNBOOK.md** (failover+failback). **DRILL PASSED end-to-end:** failover.sh --force → replica promoted RW in ~3s → `/login`=200 + DB `WRITE_OK` (~14s RTO) → hub untouched (in_recovery=false) → failback re-clone → streaming restored, lag 0, KB match (31202), standby stopped. Hub never affected. TODO self-sufficiency: also copy failover.sh+runbook to a git remote + the owner's machine (boston-2 copy alone dies if boston-2 is the problem). (Original plan below.)
- **Goal:** failover runnable when the hub is gone.
- **Steps:** `/opt/archie-dr/failover.sh` on boston-2 (promote replica → start platform → flip DNS via **Hostinger API** → verify), idempotent + split-brain-guarded. Replicate runbook+script to **(a) boston-2, (b) git remote, (c) owner's reach** (laptop/printed SSH one-liner). The `.claude/plans/` copy on the hub does NOT count.
- **Verify:** **DRILL** — promote boston-2 in a planned test, confirm login/KB/core modules, then fail back. Run `ssh root@2.25.133.122 /opt/archie-dr/failover.sh` from a non-hub machine.
- **Risk:** med (touches prod DB/DNS in the drill — scheduled window). **Effort:** ~1–2 days.

## 🟡 Phase 5 — Mesh + ingress + cluster takeover — INGRESS STAGED (2026-06-02), rest gated
DONE/staged on boston-2:/opt/archie-dr/: `ingress/Caddyfile` (reverse_proxy 127.0.0.1:3000) + `ingress/docker-compose.caddy.yml` (restart:no — started by failover.sh) + `dns_flip.sh` (Hostinger DNS API → platform A=2.25.133.122). Caddy config VALID, scripts syntax-OK, both WIRED into failover.sh. **GATED:** (1) owner must stage `/opt/archie-dr/.hostinger_token`; (2) the DNS flip is UNTESTABLE without breaking prod (verify payload vs a throwaway subdomain; real verification only at actual failover); (3) Caddy LE cert provisions only post-flip. ### Phase 5b design — "fleet follows boston-2" (scoped 2026-06-02; build+drill DEFERRED to a fresh session)
Two SEPARATE problems — don't conflate them:
- **5b-core (app-level, lower risk) — repoint node HUB_URL.** Each node hardcodes `HUB_URL/BRIDGE_URL=http://100.64.0.4:3000` (`/opt/archie-node/.env`). The Tailscale **data plane is peer-to-peer**, so `100.64.0.10` stays reachable from every node even with the hub coordinator down. So `failover.sh` (or the operator) SSHes each surviving node, sets `HUB_URL/BRIDGE_URL→http://100.64.0.10:3000`, restarts `archie_outpost_sync`. **No Headscale change.** ⚠️ GOTCHA: do NOT use a MagicDNS name (`*.mesh.archie`) — MagicDNS is served BY Headscale ON the dying hub, so it fails exactly when needed; use the raw mesh IP `100.64.0.10`.
- **5b-standby (control-plane, HARD/risky) — Headscale standby.** `headscale/headscale:0.25`, config `/mnt/archie_brain/headscale/{config.yaml,acl.json}`, state in docker volume `archie_headscale_data`. Only needed for LONG outages (re-auth / new node joins / IP reassignment); existing tunnels persist a long time without it. Requires replicating Headscale state + re-pointing each node's tailscale `--login-server`. DEFER — drill-required, separate project.

**Why deferred:** an untested fleet-repoint in the critical `failover.sh`, touching production node configs, can't be verified without disrupting live nodes (a repointed node heartbeats to the normally-stopped boston-2 → appears offline to the hub). Build it FRESH: repoint ONE node as a drill (boston-2 platform up), confirm it heartbeats to boston-2, revert, THEN wire into failover.sh. Manual repoint procedure is in boston-2:/opt/archie-dr/DR_RUNBOOK.md.

(Original plan below.)
- **Goal:** users AND the fleet reach the recovered platform.
- **Steps:** **floating hub identity** — a mesh DNS name (`hub.mesh`) or boston-2 assuming `100.64.0.4` after the hub is fenced, so failover flips ONE record not every node's `.env`; **Headscale standby** on boston-2 (replicate state) so the mesh stays joinable/healable; **Caddy/NPM** on boston-2 to serve the platform publicly. boston-2's dispatcher then schedules surviving nodes.
- **Verify:** with hub fenced, a surviving outpost/Starship heartbeats to boston-2 and runs a dispatched task.
- **Risk:** med (mesh routing). **Effort:** ~2 days.

## Phase 6 — Failback discipline
- **Goal:** return to FULL POWER without split-brain.
- **Steps:** rebuild hub (or its DB) as a **replica of boston-2**; in a maintenance window switch writes back to the hub, demote boston-2. **Fence the dead primary before any promote.**
- **Verify:** post-failback, hub is primary, boston-2 streaming again, one primary only.
- **Risk:** med. **Effort:** ~1 day + runbook.

## Phase 7 — Detection + automation  *(makes it "runs when up and down" automatically)*
- **Goal:** hands-off (or one-tap) recovery.
- **Steps:** **watchdog on boston-2** pings the hub over mesh; on >N-min loss it alerts (Telegram via boston-2's own egress) and — confirmed by the **surviving-node quorum** (avoids promoting on a blip) — triggers failover. External uptime monitor as belt-and-suspenders. Optionally Patroni/repmgr for managed promotion. **Periodic DR drills** (quarterly).
- **Verify:** simulated hub-down auto-promotes within target RTO; false-blip does NOT promote.
- **Risk:** med-high (automation can misfire) — build only after Phase 4 manual is proven. **Effort:** ~2–3 days.

---

## Honest status & caveats
- **Built today:** only Phase 1. Phases 2–7 are designed, not built — the platform **cannot** fail over yet.
- **No GPU on boston-2** → accept degraded inference in DR.
- **Split-brain** is the top risk → single-primary fencing is mandatory in Phases 4/6/7.
- **boston-2 is root@** (not kytran@) — note in runbooks; optionally add a kytran user.
- The brain DB + platform must fit in 32 GB (fine today ~1.3 GB DBs; watch KB growth).
- **Trust only after a real drill** (Phase 4 verify).

## Recommended next action
**Phase 2** — install Postgres 16 on boston-2 and start streaming replication from the hub over the mesh. Read-only, zero risk to the hub, delivers read-survival. I'll script + verify (lag check) before anything else.
