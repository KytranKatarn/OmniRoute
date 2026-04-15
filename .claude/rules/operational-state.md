# Operational State — DO NOT SKIP

## Product Registry (What Exists — Don't Rebuild)

| Product | Port | Subdomain | Container | Location |
|---------|------|-----------|-----------|----------|
| ARCHIE Platform | 3000 | platform.kytranempowerment.com | archie_platform | Hub |
| A.R.C.H.I.E. Comms | 3002 | archie.kytranempowerment.com | archie_comms | Hub |
| Market Watch | 8101 | market.kytranempowerment.com | kytran_market_api | VPS |
| Civic Watch | 8099 | civic.kytranempowerment.com | kytran_watch_api | VPS |
| Legal Watch | 8100 | legal.kytranempowerment.com | kytran_legal_api | VPS |
| Gov Watch | 8102 | gov.kytranempowerment.com | kytran_gov_watch | VPS |
| The News | 8103 | thenews.kytranempowerment.com | kytran_news | VPS |
| Business Suite | 8091 | business.kytranempowerment.com | kbs_app | Hub |
| System Operations | 8085 | server.kytranempowerment.com | kytran-system-operations | Hub |
| Stalwart Mail | 25/465/587/993 | mail.kytranempowerment.com | stalwart_mail | Hub |
| CORS Proxy | 8098 | proxy.kytranempowerment.com | kytran_cors_proxy | Hub |
| Headscale Mesh | 8095 | mesh.kytranempowerment.com | archie_headscale | Hub |
| AdGuard DNS | 53/5354 | adguard.kytranempowerment.com | network_adguard | Hub |
| Nagios Monitoring | 8082 | nagios.kytranempowerment.com | monitoring_nagios | Hub |
| C.R.E.E.D. Governance | 8086 | creed.kytranempowerment.com | kytran_creed | Hub |
| NPM Proxy | 80/443 | proxy.kytranempowerment.com | nginx_proxy_manager | Hub |
| Plex | 32400 (host) | — | media_plex | Hub |
| Jellyfin | 8096 | — | media_jellyfin | Hub |
| Sonarr | 8989 | — | media_sonarr | Hub |
| Radarr | 7878 | — | media_radarr | Hub |
| Prowlarr | 9696 | — | media_prowlarr | Hub |
| Overseerr | 5055 | — | media_overseerr | Hub |
| SABnzbd | 8083 | — | media_sabnzbd | Hub |

## VPS / Fleet

| Node | IP | Mesh IP | Role | Containers |
|------|-----|---------|------|------------|
| Hub | 192.168.1.200 | 100.79.11.3 | Primary server | All above |
| US Outpost | 76.13.107.109 | 100.64.0.1 | Fleet node | Caddy, KSO, SMTP relay, Market/Civic/Legal/Gov Watch, The News |
| Node .246 | 192.168.1.246 | — | Offline | RTX 3070, 32GB RAM, awaiting Docker |
| Node .245 | 192.168.1.245 | — | Offline | RTX 3070, fresh machine |

## DNS (kytranempowerment.com)

- Root (@) → Hostinger CDN (cdn.hstgr.net)
- 22 subdomains pointing to hub (153.68.195.85) — NPM reverse proxy active, SSL on all proxy hosts
- 7 subdomains pointing to VPS (76.13.107.109): market, civic, legal, gov, thenews, outpost-us, relay — ALL LIVE
- Hub public IP: 153.68.195.85
- NPM: 17 proxy hosts, all SSL forced (cleaned 2026-04-13 — removed portainer, mdm, code, devhq, *.fleet DNS + 7 dead proxy hosts)
- `creed-ai.org` → Hostinger shared hosting (separate domain)

## Consciousness Module Status

- Embedding loop: ENABLED, runs every 30 min, 200 items/batch
- Analysis loop: ENABLED, runs every 30 min, 10 items/batch, uses mistral:7b
- Translate loop: ENABLED but blocked (no agent has translate skill)
- Loops CANNOT auto-disable (kill switches removed 2026-04-02, Decision #369)
- MCP sessions store to knowledge_base directly (not ai_conversations)

## 3-System Architecture (MANDATORY — See project_core-architecture-vision.md)

1. **Autonomy Module** — runs scheduled jobs (agent_loop.py)
2. **Department HQ** — manages agents, departments, fleet, dispatch, jobs (11 tabs incl. Fleet)
3. **AI Bridge** — model routing, embeddings, knowledge analysis (`ai_bridge/`). Dispatcher moved to Dept HQ (Decision #440).

*Starbase Command merged into Department HQ Fleet tab (2026-04-08). No longer a separate system.*

## Before ANY Infrastructure Change

- NEVER touch VPS SSH/keys/passwords without user approval
- NEVER modify docker-compose.yml without warning (triggers rebuild, DNS downtime)
- ALWAYS check if product runs on VPS before making local-only changes
- ALWAYS search KB for existing mistakes before attempting infrastructure
