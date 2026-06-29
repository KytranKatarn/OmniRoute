# Watch-Series Edge Funnels — DIY Regional Edge / CDN (design scope)

**Status:** Phase 0 SHIPPED + verified (#4320, PR #1915, 2026-06-24; re-verified live cont-105 2026-06-28).
Layer-1 routing DECIDED 2026-06-28: **self-hosted gdnsd on our own outposts** (no third-party provider).
Phases 1/3 gated on the edge cutover + actual traffic growth.
**Origin:** 2026-06-18 what-the-fact.com scraper-overload incident (see handoff cont-27,
KB mistake #273994). Owner direction: use **our own network + nodes**, avoid recurring $$.
**Likely home project:** #364 (WTF Site Quality) — but the capability is **cross-product**
(all Watch products: gov/civic/legal/market/wtf).

---

## Problem & why this exists
A distributed scraper swarm (~40 IPs, faked browser UAs, hammering `/news`) saturated the
single `wtf-consumer` on Citadel and took the site down for everyone. **Per-IP rate-limiting
(Caddy or app) can't stop a distributed swarm** — the effective defenses are (a) edge caching
so the origin only sees misses, (b) a global throughput cap, and (c) geographic load spread.
We own a global fleet (Beacon + 4 outposts) and want to use it as our own edge layer rather
than pay a CDN.

## Already shipped (today, so we are NOT exposed while this is designed)
- `wtf-consumer` workers **4 → 8**; `/news` **result cache** (per-worker TTL, tier-safe —
  caches data, renders per-request); per-IP `/news` limiter (real client IP via XFF, fail-open);
  `www.what-the-fact.com` cert. Current ~2 req/s load is handled with headroom. **This project
  is for growth / global latency / DDoS resilience, NOT an outstanding outage.**

## Goal / non-goals
- **Goal:** a self-hosted, multi-region edge layer that fronts the Watch products — caches,
  rate-limits (incl. a *global* cap), spreads load by region, and shields/locks-down the origin.
  $0 recurring where possible.
- **Non-goals:** anycast/BGP (we don't own IP space); replacing Citadel as origin; per-user
  personalization at the edge (Watch feeds are public/tier-gated at render, not at edge).

---

## Architecture — three layers

### Layer 1 — Routing (get each region to its nearest healthy funnel) ⚠️ THE PIVOTAL DECISION
This is the hard part and the thing a CDN actually sells. Needs **GeoDNS + health checks**:
the DNS answer for `what-the-fact.com` differs by requester location (UK→outpost-uk,
SG→outpost-singapore, NA→Beacon/Citadel) AND a dead funnel auto-drops from rotation.

**Hostinger DNS cannot do geo or health-aware routing.** Plain round-robin A-records (the only
basic-DNS DIY option) ignore geography AND keep routing ~1/N of users to a down node → not
production-grade. So the project hinges on choosing a routing solution:

| Option | Geo | Health | Cost | Notes |
|--------|-----|--------|------|-------|
| **GeoDNS provider** (Route53 / NS1 / ClouDNS / Bunny) for the Watch domains only | ✅ | ✅ | ~$0.50–few $/mo or free-tier | Keeps Hostinger for everything else; our outposts stay the edges. **Primary path for "our infra".** |
| **Cloudflare free tier** | ✅ (anycast) | ✅ | $0 | But CF *becomes* the edge → our outpost funnels are then redundant. Least engineering; third-party. The honest "for a global edge, CF free is less work than DIY." |
| **Round-robin A-records** (Hostinger) | ❌ | ❌ | $0 | Crude; routes to far/dead nodes. Acceptable only as a stopgap, not the target. |
| **Anycast / BGP** | ✅ | ✅ | infra-heavy | Not feasible on VPS — we don't own IP space. |

**✅ DECISION (2026-06-18, owner): our-outpost edges + a GeoDNS provider.** (Cloudflare-as-edge
rejected — keep it on our own infra.)

**✅ SUB-DECISION SUPERSEDED (2026-06-28, owner, cont-105): SELF-HOSTED GeoDNS on our own
outposts — NO third-party provider.** The "use our own network, $0 recurring" direction is met by
running an open-source authoritative GeoDNS server on the fleet (the design originally under-explored
full self-hosted authoritative geo; the managed-provider shortlist is kept below as FALLBACK only):
- **Engine: gdnsd** — purpose-built (MaxMind GeoLite2 geo routing + built-in health-checked failover;
  PowerDNS+geoip / CoreDNS+geoip are equivalents). $0, self-hosted, featherweight.
- **Nameservers (≥3, geo-spread):** ns1=Outpost-US (NA, 76.13.107.109), ns2=Outpost-UK
  (EU, 2.24.130.153), ns3=Outpost-Singapore (APAC, 156.67.217.86); Outpost-Lithuania = optional 4th.
  A resolver retries another NS if one dies → the domain stays up.
- **Edges per region:** NA→Beacon, EU→Outpost-UK (Lithuania failover), APAC→Outpost-Singapore.
- **Reuse the egress geo-map** (`egress_catalog_service` / `remote_nodes.extra_capabilities.socks5_egress`,
  5/6 nodes already mapped) as the single region→node source of truth.
- **Mechanic:** delegate ONLY the Watch domains (what-the-fact.com/.tech first; gov/civic/legal/market
  later) to our gdnsd nameservers at the registrar (glue records) — keep `kytranempowerment.com`
  on Hostinger untouched.
- **The trade we accept:** we now OWN authoritative-DNS uptime (no anycast SLA). A dead *edge* is
  graceful (cache/failover); a dead *DNS layer* takes the whole domain dark (resolvers cache the
  failure for the TTL) — so the NS layer is the thing to over-engineer (≥3 geo-spread NS, sane TTLs,
  monitor the monitors).
- **Known gaps:** APAC is a single node (Singapore) — failover degrades latency, not uptime, until a
  2nd APAC node; **Outpost-US `remote_nodes.hostname` = stale `172.27.0.1`** (docker bridge) must be
  corrected to `76.13.107.109` before it can be a glue'd nameserver (task filed).

**FALLBACK (only if we ever decide NOT to own DNS uptime) — a managed GeoDNS provider:** recommend
**AWS Route 53** (geo + latency + health checks + best API; ~$3–5/mo incl. non-AWS health checks —
verified 2026-06-28). Strict-$0 alt: **NS1 free Developer** (⚠ geo-steering/health may be gated + post-IBM
free-tier longevity risk). **ClouDNS GeoDNS** ~$9.95/mo (incl. explicit Canadian-region geo). Delegate
ONLY the Watch domains; keep `kytranempowerment.com` on Hostinger untouched.

### Layer 2 — The funnels (each edge node)
Per funnel: **cache + rate-limit + reverse-proxy to origin**.
- **Engine:** prefer **nginx** (`limit_req` + `proxy_cache` are built-in, battle-tested — no
  custom `xcaddy` build). Caddy is fine too but `rate_limit` needs a custom module build.
- **⚠️ Port constraint (discovered 2026-06-18):** Beacon and the outposts **already run a Caddy
  on 443** for their existing ingress (Beacon = ~20 hub services; outpost-us = api proxy, etc.).
  So a Watch edge is NOT a clean separate add-on per node — it either (a) integrates into that
  node's existing proxy config, or (b) runs as a distinct proxy on a node/port we free up. This
  is a per-node design item, not a blocker.
- **Cache:** reuse today's lesson — cache the *public* feed data, render/serve per-request so
  tier/paywall chrome stays correct. Edge cache TTL ~30–60s; vary on the filter query only.
- **Rate-limit:** per-IP (`limit_req_zone $binary_remote_addr`) + a **global** zone (constant
  key) on `/news` per edge → aggregate origin load = num_edges × per-edge-cap.

### Layer 3 — Origin lockdown
Citadel `wtf-consumer` (and the other Watch origins) must accept traffic **only from our edge
nodes** (mesh-only + firewall), so a scraper can't bypass the edges by hitting the origin IP
directly. Today `what-the-fact.com` → Citadel directly; in the funnel model the public DNS
points at the **edges**, and the origin is mesh-internal.

## Load balancing — where it happens
- **Geo level (inbound):** Layer-1 GeoDNS spreads users across regional funnels = the inbound
  load balancer.
- **Origin level:** with edge caching the single origin only sees cache-misses; if that ever
  grows, edges balance across multiple origin replicas — but Watch consumers share the hub
  `wtf`/product DBs, so **caching beats replicas** for our scale.

## TLS
Each edge provisions its own LE cert for the Watch domains it fronts (HTTP-01 works as long as
DNS routes the challenge to that edge; or use DNS-01 with the GeoDNS provider's API). www +
apex per domain.

## Multi-role outposts ⚠️ (they already do MORE than ingress — design must coordinate)
The outposts are NOT single-purpose. They already run the **outbound SOCKS5 egress fabric**
(S.C.O.U.T. browse-from-country: `node_socks`, unauth serjs SOCKS5 on `0.0.0.0:1080`, gated
mesh-only by a DOCKER-USER iptables DROP — Docker bypasses UFW; live on all 5 outposts), and
**Playwright browsing *out of* those nodes** is on the roadmap. Adding an INBOUND edge role makes
each outpost triple-duty — the edge design MUST account for:

- **Resource budget (small nodes!):** outposts are ~8 GB CPU VPS. The edge (nginx cache+limit) is
  light, but **Playwright browsers are heavy** (RAM/CPU). Do NOT blindly co-locate a busy public
  edge + heavy browser sessions on the same tiny node — set capacity rules, or keep the heaviest
  browse-from nodes distinct from the busiest edge nodes.
- **Firewall coexistence (inbound vs outbound):** SOCKS5 egress is **mesh-only** (iptables
  DOCKER-USER DROP). The new edge is **public :443**. They must coexist: the public edge must NOT
  expose :1080, and inbound rules must not weaken the mesh-only gate. Re-verify iptables ordering
  after adding any edge (KB mistake #272166 — Docker bypasses UFW, Chromium can't auth SOCKS5).
- **IP reputation (the big one):** an outpost IP that is BOTH an inbound edge (serving
  what-the-fact.com) AND an outbound scraper/browser can get **flagged/blocklisted by the sites it
  scrapes** → which then degrades it as an inbound edge. Consider separating the scrape-egress IP
  from the public-edge IP (dedicated egress vs edge nodes, or secondary IPs per node).
- **Synergy — reuse the geo map, don't build a second one:** the egress fabric ALREADY maps
  node↔country (`egress_catalog_service` / `proxy_selector`,
  `remote_nodes.extra_capabilities.socks5_egress`). The SAME mapping should feed the GeoDNS
  **region→edge** routing (Layer 1) — one source of truth for "which outpost represents which
  region," shared by outbound egress AND inbound edge.
- **Cross-ref before assigning edge roles:** confirm S.C.O.U.T.'s current/planned
  browse-from-outpost design (DHQ S.C.O.U.T. tab — egress + browser-profile services) so the two
  roadmaps don't collide on the same nodes.

## Phasing (incremental, low-risk)
1. **Funnel #0 — Beacon / North-America (no GeoDNS needed yet):** stand up one edge
   (nginx cache+limit) fronting `what-the-fact.com`, DNS → it, origin locked to mesh. Validates
   the whole pattern with a single region (everyone routes to one edge → no geo decision yet).
   Instant rollback = revert the A-record to Citadel.
2. **Decide Layer-1 routing** (GeoDNS provider vs CF-free). *Gates step 3.*
3. **Add regional funnels** (UK, Singapore, Lithuania) once geo-routing exists.
4. **Generalize to the other Watch products** (gov/civic/legal/market) — same edge template.

## Right-sizing / when to actually build
- Today: ~2 req/s, handled. **Don't build yet just for this.**
- Build when: WTF/Watch traffic grows materially, real DDoS appears, or we want global
  low-latency for real users across the Watch suite. Then Phase 1 first, decide routing, expand.

## Open decisions for the owner
1. ✅ **Routing layer — FULLY DECIDED.** (a) our-outpost edges + GeoDNS (2026-06-18); (b) SUB-DECISION
   2026-06-28: **SELF-HOSTED gdnsd on our own outposts** (ns1=Outpost-US / ns2=Outpost-UK /
   ns3=Outpost-Singapore), NO third-party provider. Managed provider (Route 53) kept as fallback only.
2. ✅ **Edge engine — DECIDED:** nginx (Phase 0 #4320 shipped on it — built-in limit_req + proxy_cache).
3. **Scope (still open):** WTF-only first, or design the template for all Watch products from the start.

## Safety / rollback invariants
- Public DNS A-record is the master switch — reverting it to the direct origin is instant
  rollback at every phase.
- Never touch a shared ingress (Beacon host-Caddy / Citadel `archie_ingress_caddy`) in place
  without `caddy validate` + keeping the prior image/config + re-verifying ALL fronted services.
- Origin lockdown must be additive-then-flip (open mesh path first, verify edges reach origin,
  THEN restrict public) so we never strand the origin.

---
*Author: Claude (cont-27, 2026-06-18). Companion to handoff cont-27 + KB mistakes #273994
(WTF overload) / #273993. Edge defenses already live; this is the strategic follow-on.*
