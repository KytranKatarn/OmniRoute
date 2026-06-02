# Hub High-Availability — Phased Plan
*Goal: if the Starbase (hub) goes down, the cluster stays as up as possibly. Survive hub failure.*
*Source audit: `.claude/hub-spof-dependency-audit.md` (2026-06-01). Owner: Kytran.*

## Guiding constraints (don't fight these)
- **GPU lives only on hub + Starships** — heavy inference/ComfyUI can't move to outposts. Accept cloud fallback for AI during a hub outage.
- **Outposts are 7.8 GB CPU** — too small for the `archie_database` working set (31k KB rows + pgvector). DB replicas go on **Starship-246 (29 GB)** or a bigger VPS, never a small outpost.
- **`archie_database` is the brain** — KB, auth, dispatch, every hub module read it. It's the ultimate SPOF.
- **Good news from the audit:** all 4 Watch products already keep data locally. Only WTF's DB is on the hub. So Phase 0 is small.

## Effort vs value (read this first)
| Phase | Buys | Effort | Risk |
|---|---|---|---|
| **0 — Decouple the edge** | Watch+WTF serve public/cached content during a hub outage | days | low |
| **1 — Auth survives a blip** | Logged-in users keep working through short hub outages | ~1 week | medium |
| **2 — Postgres HA (the brain)** | KB/auth/dispatch DB no longer a total-loss SPOF | weeks | high |
| **3 — Mesh + ingress redundancy** | Fleet self-heals; products reachable without hub NPM | ~1 week | medium |
| **4 — Standby platform (true HA)** | Hub can fully die, org keeps operating (degraded) | weeks+ | high |

**Phases 0–1 deliver ~80% of practical resilience for ~20% of the effort. Start there.**

---

## Phase 0 — Decouple the edge (cheap, highest ROI)
**Outcome:** a hub outage stops killing VPS-hosted products' core browse experience.

- **0.1 Move WTF's DB off the hub.** It's the only product DB on the hub (`WTF_DATABASE_URL=…@100.64.0.4/wtf`).
  - Stand up a Postgres on outpost-boston (or reuse `gov_watch_db`'s engine with a separate `wtf` DB).
  - `pg_dump` the hub `wtf` DB → restore on the VPS → repoint `WTF_DATABASE_URL` to local → `docker compose up -d --build` the 3 wtf containers.
  - Keep a hub-side copy/replica only if the hub `wtf_hub` module still needs reads (it can read the VPS DB over mesh, or degrade).
  - **Caveat:** WTF also calls `CREED_API` (hub) + `WTF_HUB` (hub) for governance widgets — those degrade gracefully (Phase 0.2), they don't block the feed.
- **0.2 AI graceful degradation (all products).** Wrap every `*_BRIDGE_URL` call so an unreachable hub = feature disabled + friendly notice, not a 500. Per-product code guard (timeout + try/except → "AI temporarily unavailable").
- **0.3 ✅ DONE (this audit):** confirmed gov/market/legal/civic data is all local. No action.

**Verify:** stop the hub (or block 100.64.0.4 from the VPS), confirm each Watch product + WTF still serves its public pages.

---

## Phase 1 — Auth survives a hub blip (moderate)
**Outcome:** users already logged in keep working when the hub is briefly down.

- **1.1 Local session-token validation.** Today every request round-trips to the hub IdP (`KYTRAN_AUTH_URL`/`AC_API_URL`). Switch to validating the existing session JWT *locally* (cache the IdP public key / shared secret on each product). Existing sessions survive a hub outage.
- **1.2 New-login fallback policy.** New logins still need the hub IdP — accept that, show a "sign-in temporarily unavailable, existing sessions OK" banner during an outage.
- **1.3 (optional) Tier cache.** Products already store tier locally (set via `/api/internal/set-tier`); ensure they read the cached tier, not a live hub call, on each request.

**Verify:** log in, kill the hub, confirm an authenticated session keeps browsing gated content.

---

## Phase 2 — Postgres HA for `archie_database` (the big one)
**Outcome:** the brain DB survives hub hardware failure; recovery path exists.

- **2.1 Streaming replica on Starship-246 (29 GB).** `pg_basebackup` + WAL streaming from hub `archie_database`. (Outposts can't hold it.)
- **2.2 Read survival immediately** — replica serves reads. **Write failover is manual at first** (promote replica, repoint `DB_HOST`). Document the runbook.
- **2.3 Externalize recovery inputs** — secrets, config, `docker-compose.yml`, model cache (`/mnt/llm_drive` already separate). So a rebuilt platform can point at the replica.
- **2.4 (later) Automated failover** — Patroni/repmgr if/when manual proves insufficient.

**Reality check (#250231):** this is real DB engineering with owner hands-on for the VPS/Starship steps. Do it on a maintenance window, never blind.

---

## Phase 3 — Mesh + ingress redundancy (moderate)
**Outcome:** fleet heals and products stay reachable without the hub's NPM.

- **3.1 Headscale standby / degraded-mode plan.** Existing tunnels persist P2P during a control-plane outage; document the re-auth/preauthkey path, or run a standby coordinator.
- **3.2 Secondary ingress.** Each product already has Caddy on its VPS — ensure public DNS can fail over to the VPS Caddy so routing doesn't depend solely on hub `nginx_proxy_manager`. (Watch/WTF DNS already points at the VPS; this is mainly for hub-hosted sites.)

---

## Phase 4 — Standby platform / true HA (aspirational)
**Outcome:** closest to "hub fully dies, org keeps operating (degraded)."

- **4.1 Stateless-ify `archie_platform`** (mostly is; config + mounts assume hub) → run a warm standby pointed at the Phase-2 replica in read-only/degraded mode.
- **4.2 Distribute the dispatch queue** (the hardest stateful piece).
- **4.3 Accept GPU/ComfyUI stay hub/Starship-anchored** — cloud fallback during hub outage.

---

---

## Phase 0.1 SCOPING RESULT (2026-06-01) — naive WTF DB move is SUPERSEDED
Scoping the "move WTF's DB to the VPS" step found two blockers, so we **do not** do that move:
- **Parliamentary coupling:** the hub `wtf` database is 1331 MB but only ~160 MB is `wtf.*`; **1171 MB is `parliament.*`** (Elections Canada, 4.76M rows, Project #348). `wtf.*` has **2 cross-schema FKs into `parliament.mps`** (`article_mp_tags.mp_id`, `claim_tracker.mp_id`) — the live Promise-Tracker/MP-tagging integration; WTF ingest also *writes* parliament data. You can't FK across two DB servers → moving `wtf.*` off-hub severs it.
- **VPS RAM:** outpost-boston has ~1.6 GB free (already runs 4 Watch + 3 WTF + node stack). Risky to add a Postgres engine.
- **Conclusion:** WTF's data is intentionally interwoven with the Parliamentary platform (Master Vision #343, shared entity graph). It belongs in the core brain DB. Protect it via an HA **replica** of the brain DB (below), not a lift to a tiny VPS.

---

## Distributed Data Topology — the "Borg" question, answered for THIS cluster
**Constraint reality:** global nodes are 50–250 ms apart and outposts are 7.8 GB → a single transparent collective DB across *all* nodes is the wrong fit (WAN write latency + tiny members). The right shape is **a small low-latency core + an edge**, with selective replication of shared lookups.

```
TIER A — CORE (writes + the brain), low latency
  ┌ Hub (Montreal, 128 GB, GPU) ........ PRIMARY  archie_database
  │     (KB, auth, dispatch, parliament.*, wtf.*)  ← system of record
  ├ Starship-246 (Montreal LAN, 29 GB) . HOT STANDBY replica (streaming)
  │     → survives hub MACHINE death; fast promote (same site)
  └ [Upgraded VPS, 16–32 GB, OFF-SITE] . OFF-SITE replica (streaming)
        → survives the whole Montreal SITE going down (power/ISP/DR)

TIER B — PRODUCT-LOCAL (each product owns its data, on its node)
  gov_watch→gov-watch-db · market/legal/civic→local SQLite   ✅ already
  WTF→ stays in CORE brain DB (parliament coupling), covered by Tier A replica

TIER C — SHARED GRAPH (selective logical replication of SMALL lookup tables)
  parliament.mps (small) ──▶ replicated to nodes that need MP lookups (VPS)
  parliament.ec_contributions (1.1 GB) stays CORE-only
  → "entity graph available everywhere" without copying everything

TIER D — EDGE (small global outposts, 7.8 GB)
  no DB hosting · serve regional reads + small-model inference
  (optional per-product read-replica if regional latency matters)

GPU / inference: hub + Starships only; cloud fallback. NOT distributable.
```

### What survives which failure
| Failure | Outcome with this topology |
|---|---|
| Hub *machine* dies | Promote Starship-246 replica → brain back (incl. WTF). Products on VPS already independent. |
| Whole Montreal *site* dies (power/ISP) | Only the **off-site VPS replica** survives → this is the case a VPS upgrade buys. |
| A VPS dies | Only that VPS's local products affected; brain untouched. |
| Network partition | Products keep serving local reads; brain writes queue/degrade. |

### Concrete steps (this refines Phase 2 + fixes the WTF coupling)
1. **Brain replica on Starship-246** — `pg_basebackup` + WAL streaming from hub `archie_database`. Read survival immediately; documented manual promote. (Covers WTF + parliament + KB + auth in one move.)
2. **[If VPS upgraded] off-site replica** on the upgraded VPS — second streaming replica for site-level DR.
3. **Relax the 2 cross-schema FKs to app-level** (`article_mp_tags`/`claim_tracker`.mp_id) + **logical-replicate `parliament.mps`** (+ other small shared lookups) to the VPS, so WTF/Parliament features resolve locally without a cross-server FK. This is the real "decoupling" — surgical, not a full DB move.
4. **Auth caching** (Phase 1) so products survive a brief core outage.
5. **Promote/failover runbook** documented + drilled.

---

## VPS upgrade — is it worth it? (short answer: yes, for ONE specific job)
**The single highest-value HA upgrade is making one *geographically separate* VPS a real off-site brain-DB replica.** A same-LAN Starship replica protects against the hub *box* dying, but NOT against the whole Montreal site losing power/internet. Only an off-site node does that — and that node needs RAM to hold the brain DB working set.

- **Plan:** Hostinger KVM2 (8 GB, current outpost-boston) → **KVM4 (16 GB)** or **KVM8 (32 GB)**. Pick the node that's *not* in Montreal (e.g. upgrade an EU/Asia outpost, or outpost-boston) to be the off-site replica host.
- **What it unlocks:** Tier-A off-site replica (true disaster recovery) + headroom to stop the current ~1.6 GB-free memory pressure.
- **Caveats:** Hostinger KVM = **no GPU** (inference still hub/Starship + cloud). It's a recurring cost — justify it specifically as *disaster-recovery insurance for the brain DB*, not for compute.
- **Cheaper alternative if DR isn't urgent:** skip the upgrade, put the only replica on Starship-246 (free, already owned, 29 GB) — covers hub-box failure but not site failure.

## Recommended sequence
1. **Phase 1 auth-caching + Phase 0.2 AI-degradation** (no infra risk, protects ALL products) — start here.
2. **Brain replica on Starship-246** (Phase 2.1) — biggest HA win, no new cost.
3. **Decide on a VPS upgrade** for an off-site replica — only if site-level DR matters to you.
4. **Parliament.mps selective replication + FK relax** — when the WTF/Parliament integration needs to work cross-node.

## What needs the owner (can't be Claude-only)
- VPS/DB migration steps + maintenance windows (Phase 0.1, 2)
- Any change touching production auth (Phase 1) — test on staging first
- Decision: is Starship-246 the DB-replica home, or do you want a beefier dedicated VPS?
