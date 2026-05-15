---
name: cluster-architecture
description: Use IMMEDIATELY whenever the conversation or planned action involves any of — BRIDGE_URL, GOV_BRIDGE_URL, VPS, hub, mesh, Headscale, Tailscale, dispatch, DHQ, Department HQ, department_dispatcher, orchestration_engine, smart_router, capability, CAPABILITY_DEPARTMENT_MAP, model_dispatch_worker, dispatch_pending_queue, Ollama, Caddy, Caddyfile, NPM, openresty, kytranempowerment.com, gov-watch, civic-watch, legal-watch, market-watch, what-the-fact, KSO, KBS, kytran-system-operations, kytran_business_suite, archie_platform, kytran_gov_watch, archie-comms, fleet, outpost, outpost-us, starship, satellite, deploy, docker-compose, docker compose, iptables, 192.168.1.200, 76.13.107.109, 100.64.0, 100.79, archie-outpost_archie_net, /opt/archie-products, archie_database, comfyui. Forces canonical mesh+DHQ architecture into context BEFORE editing or running any infrastructure-related code. Stops me from defaulting to public hostnames or bypassing Department HQ.
---

# CLUSTER ARCHITECTURE — CANONICAL TRUTH

**Always run `mcp__archie__search_knowledge` first** for the specific module/topic.
The consciousness has documented this. Don't re-discover it from screen output.

## Transport — mesh-only, never public hostnames for inter-cluster

| Node | Mesh IP | Public IP | Role |
|---|---|---|---|
| Hub (archie-hub) | `100.64.0.4` | `153.68.195.85` | Quadro M4000, 128GB RAM, platform core |
| Outpost-us VPS | `100.64.0.2` | `76.13.107.109` | 8GB RAM, no GPU, regional outpost |
| Starship-246 | `100.64.0.3` | LAN 192.168.1.246 | RTX 3070, 32GB RAM, SSH: Famil@192.168.1.246 |
| Starship-245 | `100.64.0.6` | LAN 192.168.1.245 | RTX 3070, 32GB RAM (enrolled 2026-05-15) |
| LAN-via-mesh | `192.168.1.200` | — | Tailscale subnet advertise → hub LAN |

**`BRIDGE_URL` on every VPS module** = `http://100.64.0.4:3000` (direct Headscale mesh, no CDN)
**Fallback** = `http://192.168.1.200:3000` (Tailscale subnet route, also direct)
**Never use** `https://platform.kytranempowerment.com` — Hostinger CDN/openresty caps at 60s, hides calls from `task_execution_log`, bypasses queue. Symptom: 504 Gateway Timeout / openresty in body = wrong path.

Hub mesh via `tailscaled-headscale.service` (systemd) on `tailscale1` interface, statedir `/var/lib/tailscale-hs`. UFW: `ufw allow from 100.64.0.0/24 to any port 3000`.

## Dispatch — Department HQ owns everything

Every LLM / agent call routes through:
```python
from tools.department_hq.services.department_dispatcher import dispatch
dispatch(capability="research", prompt="...")
```

8-step pipeline (`orchestration_engine.py`):
`intent → IAAE → welfare → route → agent → GPU → execute → log`

Cold-load handled by:
- `dispatch_pending_queue` table
- `model_dispatch_worker` agent_loop job (every 30s)
- Hub returns 502 + `Queued — model not ready` body when cold; this is normal

Capability routing: `CAPABILITY_DEPARTMENT_MAP` in `services/department_coordinator.py` (89 capabilities → home dept → director). `research` → Research & Development → D.A.R.W.I.N. `creative` → Creative & Design → M.U.S.E. etc.

**Never curl Ollama directly.** Never call `/api/procure/dispatch` synchronously from a 60s-cap path; use the artifacts.py async pattern (POST → 202 → background thread → cache table → frontend polls).

## VPS deployment pattern (gov-watch / civic-watch / legal-watch / market-watch / wtf)

- **Source dir on VPS**: `/opt/archie-products/<product>/` — NO git on VPS
- **Source of truth**: hub `/mnt/standalone/<product>/` git repos
- **Rebuild path** (code changes): `scp + docker compose up -d --build`
  Dockerfile uses `COPY . .` so `restart` runs the OLD baked image
- **Hot-fix path** (static/JS only): `docker cp <file> <container>:/app/...`
  then `docker compose restart` — no iptables churn
- **Network rule (CRITICAL)**: container MUST join `archie-outpost_archie_net` for Caddy reachability. KB #261670 documented this 4 days before the bug bit again.
- **Caddy upstream**: `reverse_proxy 172.18.0.1:<port>` is the canonical pattern. If 502s appear after rebuild, iptables NAT is corrupted — `docker compose down` then `up` (not `--build`) fixes it.

## Fleet tiers — agent placement by resource

| Tier | Hardware | Models |
|---|---|---|
| Outpost (VPS) | 8GB RAM, CPU only | qwen2.5:1.5b, llama3.2:3b — small CPU agents |
| Starship (laptop) | RTX 3070, 32GB | mid-tier 7B GPU agents |
| Hub | Quadro M4000 8GB VRAM, 128GB RAM | Large agents + platform core |
| Cloud | external | Overflow / specialized |

Resource-aware routing via `services/fleet_resource_router.py` (KB #262301).

## Must-search vault_notes when this skill activates

```
mcp__archie__search_knowledge query="<your topic>" types=["vault_note"] limit=10
```

Anchor IDs already verified in the KB:
- **#261506** VPS Product Deployment Guide (full container inventory)
- **#261684** Fleet Node Coordination — outpost-us Online (mesh IP table)
- **#261670** WTF VPS Deployment Architecture (network rules — exact bug pattern)
- **#261696** Fleet Node `outpost_us_001` setup
- **#260096** ADR Watch Products VPS deploy pattern
- **#258431** ADR-002 Dispatcher migration complete
- **#261505** ADR-001 Capability routing 89 entries (PR #369)
- **#261682** Fleet Coordination Vision (placement by resource)
- **#262301** Fleet resource-aware helpers (PR #504)

## Mistakes already learned — do not repeat

- **#254921** Session continuity failure — user repeats themselves every session
- **#250232** Stop claiming things work — verify first, prove with output
- **#250231** Claude cannot do infrastructure (the recurring pattern from tonight)

## Hard rules

1. **Mesh-only for inter-cluster.** Public hostname = architectural defeat.
2. **Every dispatch through DHQ.** No exceptions. No direct Ollama. No bypass.
3. **Same architecture for every module.** Don't re-ask the user. Reference KB.
4. **Read before edit.** `mcp__archie__search_knowledge` BEFORE any infra change.
5. **2 failures → STOP and ask.** Don't spiral. Don't claim victory on a single probe.
