# Hub Single-Point-of-Failure / Dependency Audit
*Goal: if the Starbase (hub, 192.168.1.200 / mesh 100.64.0.4) goes down, what stays up?*
*Date: 2026-06-01 | Method: live `docker inspect` env audit + hub Postgres DB list. Read-only.*

## TL;DR
**Today, "hub down" ≈ "almost everything down."** Two independent reasons even the VPS-hosted
products can't survive alone:
1. **Auth/SSO is hub-only** — every Watch product logs users in via the hub (`KYTRAN_AUTH_URL` →
   platform). Hub down = no login anywhere, even where the data DB is local.
2. **Some product DBs physically live on the hub Postgres** (WTF; civic likely).

## Hub Postgres — databases hosted ON the hub (die with the hub)
- Databases: `archie`, `n8n`, `wtf`
- Schemas inside `archie`: `public`, `wtf`, `civic_transparency`, `gov_watch`
- → **WTF and (likely) Civic store their data on the hub.**

## outpost-boston (76.13.107.109 / mesh 100.64.0.2) — product survival matrix
| Product | Data store | Data survives hub down? | Login (SSO) | AI features |
|---|---|---|---|---|
| **gov_watch** | `gov-watch-db` (LOCAL container) | ✅ yes | ❌ hub (`KYTRAN_AUTH_URL`) | ❌ hub (`GOV_BRIDGE_URL`=100.64.0.4:3000) |
| **market** | `/app/data/market.db` (SQLite LOCAL) | ✅ yes | ❌ hub | ❌ hub (`MARKET_BRIDGE_URL`) |
| **legal** | `/app/data/legal.db` (SQLite LOCAL, confirmed) | ✅ yes | ❌ hub (`KYTRAN_AUTH_URL`) | ❌ hub (`LEGAL_BRIDGE_URL`) |
| **civic** | `/app/data/watch.db` (SQLite LOCAL, 54 MB, confirmed; no hub-5432 conn. The hub `civic_transparency` schema is stale/unused) | ✅ yes | ❌ hub (`AC_API_URL`) | ❌ hub (`CIVIC_BRIDGE_URL`) |
| **WTF** (consumer/ingest/tech) | `WTF_DATABASE_URL=…@100.64.0.4/wtf` (**HUB**) | ❌ **no** | ❌ hub | ❌ hub + CREED_API (100.64.0.4:8086) |

**Universal hub coupling (every product):**
- `KYTRAN_AUTH_URL=https://platform.kytranempowerment.com` + `KYTRAN_AUTH_INTERNAL_URL=http://100.64.0.4:3000` → **SSO/login through hub**
- `*_BRIDGE_URL=http://100.64.0.4:3000` → **AI dispatch through hub**
- `INTERNAL_API_KEY` → billing tier push from hub

## Hub-resident SPOFs (whole services that vanish with the hub)
- `archie_database` — the brain: KB (31k), auth, dispatch log, every hub module
- `archie_headscale` — **mesh control plane** (existing tunnels persist P2P briefly; no re-auth/heal)
- `nginx_proxy_manager` — routing/SSL for hub-hosted subdomains
- Co-located standalones (run ON the hub → die with it): **KBS, CREED, KSO, Media Hub, full media stack** (Plex/Sonarr/Radarr/etc.)
- WTF DB + Civic data (on hub Postgres)

## Survival verdict if the hub dies *today*
| Stays up | Degraded (data local, no login/AI) | Down |
|---|---|---|
| small-model inference on outposts/Starships (briefly, P2P) | **gov_watch, market, legal, civic** (all 4 Watch DBs are local) | **WTF** (DB on hub), KBS, CREED, KSO, Media Hub, the platform itself, media stack |

**Confirmed 2026-06-01:** all 4 Watch products keep data locally (gov→`gov-watch-db`, market→`market.db`, legal→`legal.db`, civic→`watch.db` 54 MB). **WTF is the only product whose DB is on the hub.** Remaining universal coupling = auth/SSO + AI dispatch (both hub).

## Cheapest high-impact fixes (priority order)
1. **Move WTF's DB off the hub** → onto outpost-boston (its app already lives there). Biggest single decoupling. Confirm + move civic similarly.
2. **Decentralize / cache auth** — the killer dependency. Even local-DB products can't authenticate if SSO is hub-only. Min viable: validate existing session tokens locally so logged-in users survive a hub blip; fuller: a standby auth on outpost-boston.
3. **AI graceful degradation** — products should disable AI features (not error) when `*_BRIDGE_URL` is unreachable. Cheap per-product code guard.
4. **Postgres HA for `archie_database`** (the big one) — streaming replica + failover. **Target a ≥29 GB node (Starship-246), NOT a 7.8 GB outpost** — the KB working set won't fit on an outpost.
5. **Headscale standby** — mesh control-plane redundancy so the fleet can heal without the hub.

## Open items to confirm (1 query each)
- legal: is its DB truly a local SQLite file? (env showed none)
- civic: does `kytran_watch_api` read `civic_transparency` from the **hub** Postgres? (no DB env surfaced)
