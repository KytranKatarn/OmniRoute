# Operational State — DO NOT SKIP

## Product Registry (What Exists — Don't Rebuild)

| Product | Port | Subdomain | Container | Location |
|---------|------|-----------|-----------|----------|
| ARCHIE Platform | 3000 | platform.kytranempowerment.com | archie_platform | Hub |
| A.R.C.H.I.E. Comms | 3002 | archie.kytranempowerment.com | archie_comms | Hub |
| Market Watch | 8101 | market.kytranempowerment.com | kytran_market_api | Citadel (boston-2) |
| Civic Watch | 8099 | civic.kytranempowerment.com | kytran_watch_api | Citadel (boston-2) |
| Legal Watch | 8100 | legal.kytranempowerment.com | kytran_legal_api | Citadel (boston-2) |
| Gov Watch | 8102 | gov.kytranempowerment.com | kytran_gov_watch | Citadel (boston-2) |
| What The Fact Consumer | 8103 | what-the-fact.com | wtf-consumer | Citadel (boston-2) |
| What The Fact Tech     | 8104 | what-the-fact.tech | wtf-tech | Citadel (boston-2) |
| WTF Ingest             | internal | — | wtf-ingest | Citadel (boston-2) |
| Business Suite | 8091 | business.kytranempowerment.com | kbs_app | Hub |
| System Operations | 8085 | server.kytranempowerment.com | kytran-system-operations | Hub |
| Media Hub (standalone) | 8105 | media.kytranempowerment.com | mediahub_app | Hub (LIVE 2026-04-19) |
| Stalwart Mail | 25/465/587/993 | mail.kytranempowerment.com | stalwart_mail | Hub |
| CORS Proxy | 8098 | — (proxy. DNS removed 2026-06-11; container stopped) | kytran_cors_proxy | Hub |
| Headscale Mesh | 8095 | mesh.kytranempowerment.com | archie_headscale | Hub |
| AdGuard DNS | 53/5354 | adguard.kytranempowerment.com | network_adguard | Hub |
| Nagios Monitoring | 8082 | nagios.kytranempowerment.com | monitoring_nagios | Hub |
| C.R.E.E.D. Governance | 8086 | creed.kytranempowerment.com | kytran_creed | Hub |
| ~~NPM Proxy~~ **DECOMMISSIONED 2026-06-27** | — | — | ~~nginx_proxy_manager~~ removed | Beacon is the sole hub front door (ADR-853, PR #1953/#1954, KB #276161). Data retained `/mnt/HomeLab/nginx-proxy` for rollback. |
| Plex | 32400 (host) | — | media_plex | Hub |
| Jellyfin | 8096 | — | media_jellyfin | Hub |
| Sonarr | 8989 | — | media_sonarr | Hub |
| Radarr | 7878 | — | media_radarr | Hub |
| Prowlarr | 9696 | — | media_prowlarr | Hub |
| Overseerr | 5055 | — | media_overseerr | Hub |
| SABnzbd | 8083 | — | media_sabnzbd | Hub |

## Anthropic Products (External — Separate Budgets)

| Product | URL | Bucket | Use for |
|---------|-----|--------|---------|
| Claude Code | (this CLI) | All models / Sonnet only | Platform dev, terminal work |
| Claude Design | https://claude.ai/design | **Claude Design** (separate weekly quota, free with Max) | Mockups, prototypes, slides, LCARS layout exploration (Project #223) |
| claude.ai chat | https://claude.ai | All models / Sonnet only | Same bucket as Claude Code |

Route visual/design work to Claude Design — it doesn't touch Claude Code budget.

## VPS / Fleet

| Node | IP | Mesh IP | Role | Containers |
|------|-----|---------|------|------------|
| Hub | 192.168.1.200 | 100.79.11.3 | Primary server | All above |
| US Outpost | 76.13.107.109 | 100.64.0.2 | Fleet node (infra only) | Caddy (archie_outpost_proxy — serves api.kytranempowerment.com → hub mesh), SMTP relay (mail egress, PTR relay.kytranempowerment.com), node_socks, outpost_sync, node_api. NO product stacks (location audit 2026-06-11: all watch products + WTF live on Citadel; WTF zombie removed #4032, archive /opt/archie-products/what-the-fact-RETIRED-20260611.tar.gz) |
| Starship - Defiant - USS-246 | 192.168.1.246 | 100.64.0.3 | **Online** (verified 2026-09-08) | RTX 3070, 32GB RAM. SSH `Famil@`. ⚠️ **WINDOWS** — no bash/python3, so it cannot run `probe_hub.sh` and must NOT be used as a DR quorum vantage (#3249). |
| Starship - Runabout - USS-245 | 192.168.1.245 | 100.64.0.6 | **Online** (verified 2026-09-08) | RTX 3050 4GB, 12GB RAM. SSH `Famil@`. ⚠️ **WINDOWS** — same probe limitation as USS-246 (#3249). |

## DNS (kytranempowerment.com)

_(Audited + pruned 2026-06-11 — KB #272182. ⚠️ Verify public DNS from an EXTERNAL resolver; the hub's AdGuard split-horizon resolves many names to 192.168.1.200 locally.)_

- Root (@) + `www` → Hostinger CDN (cdn.hstgr.net)
- **Citadel (2.25.133.122)** = external front door for hub services — ⚠️ **a CONTAINER named `beacon`** (caddy:2-alpine), config on the HOST at `/opt/archie-ingress/Caddyfile` bind-mounted to `/etc/caddy/Caddyfile` inside it: platform, consciousness, business, creed, mediahub, media, jellyfin, plex, adguard, nagios, server, store, archie, bridge, claude, codex, terminal, sandbox, shop, mesh.
  ⚠️ This line said **Beacon `2.25.170.252` (host Caddy)** until 2026-09-08. That VPS was removed by Hostinger on 2026-08-28. Both halves were wrong — the host AND the mechanism — and both cost real time: the DR ingress layer ssh'd to the dead IP and ran `systemctl reload caddy` against a machine with no caddy binary, so failover could not move public traffic (#3245/#3248). Verify with `docker ps --filter name=^beacon$` **on Citadel**, not from here.
- **Citadel/boston-2 (2.25.133.122)** = products (`archie_ingress_caddy`, `/opt/archie-ingress/Caddyfile` → local containers at 172.18.0.1:<port>): gov, market, legal, civic, wtf, mail-admin(removed), mta-sts, voice.
  ⚠️ **`mail.` is NOT here — it is HUB-fronted (192.168.1.200).** This line said "products + mail" and listed `mail` until 2026-07-26 (task #5245), contradicting the product table above, which has always correctly shown Stalwart Mail on the **Hub**. Settled by probing, not by reading: hub `192.168.1.200` → 25/587/993 **OPEN**; Citadel `2.25.133.122` → 25/993 **closed**. `mta-sts` genuinely IS on Citadel (a static policy host), which is most likely how `mail` got lumped in with it. This false claim caused a real error twice in one day: it led to `mail.` being repointed at Citadel during the #5219 recovery (a per-host grep matched `mx: mail.…` inside Citadel's MTA-STS **policy text**, not a vhost — KB #284817), and then the first draft of `scripts/dr/adguard_flip.sh` encoded the same mapping and would have repointed it again under `--apply`. `adguard_flip.sh` therefore leaves `mail.` OUT of its target map deliberately — reported, never rewritten. Do not add it back without re-probing. `voice` = reserved/planned (HA voice, no service yet). `what-the-fact.com`/`.tech` apexes also → here.
- **outpost-us (76.13.107.109)** = `api`, `relay`, `outpost-us` only (infra: api→hub mesh, SMTP relay, socks, sync, node_api). NO product stacks.
- Mail TXT/MX: SPF `v=spf1 a mx ip4:76.13.107.109 -all`, DMARC `p=reject`, `_mta-sts` (mta-sts host now SERVES the policy — **mode=testing**; enforce gated on relay cert, task #4044), `_smtp._tls`, DKIM `stalwart`+`default`, MX `10 mail` / `20 relay`, `outpost-relay`.
- ⚠️ Old hub public IP **153.68.195.85 is STALE** — hub moved (now a dynamic residential IP); external traffic enters via **Beacon**. (NPM **decommissioned 2026-06-27** — Beacon is the sole hub front door; hub :80/:443 has no listener.)
- **Pruned 2026-06-11** (#4032 follow-on): deleted `thenews`/`n8n`/`fdtest`/`ftp`/`webmail`/`mail-admin`/`brainstorm`/`proxy` A-records + legacy `zmail._domainkey` TXT (stale / no-service / ftp=takeover-risk external IP). All confirmed NXDOMAIN; Beacon Caddy blocks excised.
- ~~NPM (nginx_proxy_manager)~~: **DECOMMISSIONED 2026-06-27** (was 17 proxy hosts) — removed from `docker-compose.yml` + the infra_heartbeat/fleet_jobs critical-container watch lists; container `docker rm -f`'d. Beacon is the sole hub front door. Rollback: restore compose block + `AdGuardHome.yaml.bak` + `docker compose up`. ADR-853, PR #1953/#1954, KB mistake #276161. The Security Network 'NPM Proxy' management feature was REMOVED in **PR #1956** (merged 2026-06-27): `npm_service.py` deleted; `domain_npm_routes.py` keeps ONLY the live domain/DNS CRUD (no proxy-host endpoints); verified 2026-07-15 — zero `NPMService`/`NPM_API_URL`/`NPM_ADMIN` refs remain in `platform_v2/`. STILL-OPEN (owner-via-UI, NOT code): 2 stale AdGuard rewrites (proxy.*, brainstorm.*) — remove via the AdGuard UI, KB #276163 (do NOT text-edit the YAML).
- `creed-ai.org` → Hostinger shared hosting (separate domain)

## Consciousness Module Status

- Embedding loop: ENABLED, runs every 30 min, 200 items/batch
- Analysis loop: ENABLED, runs every 30 min, 10 items/batch, uses mistral:7b
- Translate loop: ENABLED, idle (all 8 languages fully translated — R.O.S.E.T.T.A. Lv5 handles when new keys added)
- Loops CANNOT auto-disable (kill switches removed 2026-04-02, Decision #369)
- MCP sessions store to knowledge_base directly (not ai_conversations)

## 3-System Architecture (MANDATORY — See project_core-architecture-vision.md)

1. **Autonomy Module** — runs scheduled jobs (agent_loop.py)
2. **Department HQ** — manages agents, departments, fleet, dispatch, jobs (14 tabs incl. A.R.M.A.D.A. fleet)
3. **AI Bridge** — model routing, embeddings, knowledge analysis (`ai_bridge/`). Dispatcher moved to Dept HQ (Decision #440).

*Starbase Command merged into Department HQ Fleet tab (2026-04-08). No longer a separate system.*

## Before ANY Infrastructure Change

- NEVER touch VPS SSH/keys/passwords without user approval
- NEVER modify docker-compose.yml without warning (triggers rebuild, DNS downtime)
- ALWAYS check if product runs on VPS before making local-only changes
- ALWAYS search KB for existing mistakes before attempting infrastructure
