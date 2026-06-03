# Self-Hosted Front-Door + Fleet Load Rebalance (sovereign DR ingress)

**Goal:** a stable public entry point that never chases the hub's volatile IP, built
on OUR OWN Hostinger static nodes — no third party (no Cloudflare). But it can't be
bolted on until the fleet load is rebalanced, because today one node carries
everything and the others sit idle.

> Sovereignty constraint (owner): everything stays on infrastructure we own. The
> front-door is a Hostinger VPS we run, NOT an edge service that terminates our TLS.

---

## Current reality (measured 2026-06-03)

| Node | CPU/RAM | Runs today |
|---|---|---|
| outpost-boston `100.64.0.2` (76.13.107.109) | **2c / 8GB** | KSO, gov-watch + gov_db, market, civic, WTF×3 (ingest 2GB), SMTP relay, proxy, agent stack. **+ stale `kytran_legal_api`** (legal moved to boston-2 — remove). **OVERLOADED.** |
| singapore `100.64.0.5` | 2c / 8GB | agent stack only — **idle** |
| lithuania `100.64.0.7` | 2c / 8GB | agent stack only — **idle** |
| uk `100.64.0.8` | 2c / 8GB | agent stack only — **idle** |
| boston-2 `100.64.0.10` | **8c / 32GB** | DR replica + Caddy + legal_api — **headroom** |

**Problem:** outpost-boston is a single 2-core SPOF for KSO + 3 Watch products + WTF +
email relay. The three EU/Asia outposts are wasted. boston-2 is the only big node but
it's the DR standby (shouldn't take steady product load).

---

## Phase 0 — REBALANCE FIRST (prerequisite; ties #3727)

Spread outpost-boston's load across the idle static outposts. Proposed (owner decides
final placement — this is data/product placement, their call):

| Service | From | → To (proposal) | Why |
|---|---|---|---|
| WTF (consumer/tech/ingest, heaviest) | outpost-boston | **uk** (or a roomier dedicated node) | ingest needs 2GB+; isolate it |
| gov-watch + gov_db | outpost-boston | **lithuania** | DB + app together |
| market-watch | outpost-boston | **singapore** | spread |
| civic-watch | outpost-boston | **singapore** or **lithuania** | spread |
| KSO | outpost-boston | keep, OR **boston-2** (control-plane, ties #3688) | |
| SMTP relay | outpost-boston | keep (egress); pair w/ secondary-MX #3687 | mail is special |
| stale legal_api | outpost-boston | **DELETE** (already on boston-2) | cleanup |

Geo note: keep North-American-facing products on US nodes where latency matters;
EU/Asia outposts are fine for ingest/back-office. Confirm the audience-vs-geo tradeoff
per product before moving.

After Phase 0: outpost-boston is light enough to be a front-door candidate, and the
EU/Asia nodes earn their keep.

---

## Phase 1 — the self-hosted front-door

- **Front-door = a Hostinger static VPS running Caddy** (auto-TLS). Public DNS for all
  27 hub subdomains → the front-door's static IP, set ONCE. Caddy reverse-proxies over
  the MESH to wherever each service lives:
  - normal → `http://100.64.0.4:<port>` (hub)
  - DR → `http://100.64.0.10:<port>` (boston-2)
- **Failover/failback = swap the upstream + `caddy reload`** (internal, instant) — done
  by failover.sh / failback.sh / watchdog. No public DNS change, ever.
- **A hub move = ZERO DNS work** — the hub's volatile public IP becomes invisible.

### Placement (decide AFTER Phase 0)
| Option | Pros | Cons |
|---|---|---|
| **A. New dedicated tiny US VPS** | clean, isolated, US-fast | one more box + cost |
| **B. outpost-boston (after offload)** | reuse, US | was overloaded — only viable post-Phase 0 |
| **C. boston-2** | exists, big | it's the DR node — front-door = the thing it protects (bad) |

Recommend **A or B** (US static), **not C**.

### ⚠️ All traffic flows through the front-door
Whatever node hosts it carries ALL public platform traffic (proxy hop). So it must be
(1) NOT the overloaded node, (2) NOT boston-2, (3) ideally low-latency to most users
(US). This is the whole reason Phase 0 comes first.

### HA (avoid a new SPOF)
v1 = single static front-door (Hostinger SLA). v2 = **two front-doors** (e.g. US + EU)
with health-checked DNS round-robin, so the front-door itself isn't a SPOF. Overlaps
#3681 (control-plane HA).

---

## Phasing
- **Phase 0:** rebalance outpost-boston → idle outposts (#3727); delete stale legal_api.
- **Phase 1:** stand up front-door VPS + Caddy; proxy ONE subdomain → hub over mesh; verify TLS + routing.
- **Phase 2:** upstream-swap mechanism wired into failover.sh / failback.sh / watchdog.
- **Phase 3:** migrate the 27 hub subdomains in batches (keep `hub_dns_update.sh` as fallback). Mail stays special (#3687).
- **Phase 4:** second front-door for HA (#3681 overlap).

## Relationship to other work
- Interim tool until live: `scripts/hub_dns_update.sh` (one-command move-day re-point).
- Supersedes `dns_flip.sh` / `dns_flip_back.sh` once live.
- Overlaps #3727 (rebalance), #3688 (KSO control plane), #3687 (mail MX), #3681 (HA).

*Rewritten 2026-06-03 — self-hosted (no Cloudflare), rebalance-first, per owner.*
