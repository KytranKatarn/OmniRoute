# Operational State — DO NOT SKIP

## Product Registry (What Exists — Don't Rebuild)

| Product | Port | Subdomain | Container | Location |
|---------|------|-----------|-----------|----------|
| ARCHIE Platform | 3000 | archie.kytranempowerment.com | archie_platform | Hub |
| Market Watch | 8101 | market.kytranempowerment.com | kytran_market_api | Hub (DNS→VPS) |
| Civic Watch | 8099 | civic.kytranempowerment.com | kytran_watch_api | Hub |
| Legal Watch | 8100 | legal.kytranempowerment.com | kytran_legal_api | Hub |
| Gov Watch | 8102 | gov.kytranempowerment.com | kytran_gov_watch | Hub |
| Business Suite | 8091 | business.kytranempowerment.com | kbs_app | Hub |
| System Operations | 8085 | server.kytranempowerment.com | kytran-system-operations | Hub |
| Stalwart Mail | 25/465/587/993 | mail.kytranempowerment.com | stalwart_mail | Hub |
| CORS Proxy | 8098 | — | kytran_cors_proxy | Hub |
| Headscale Mesh | 8095 | mesh.kytranempowerment.com | archie_headscale | Hub |
| AdGuard DNS | 53/5354/5355 | adguard.kytranempowerment.com | network_adguard | Hub |
| Nagios Monitoring | 8082 | nagios.kytranempowerment.com | monitoring_nagios | Hub |
| NPM Proxy | 80/443 | proxy.kytranempowerment.com | nginx-proxy-manager | Hub |

## VPS / Fleet

| Node | IP | Mesh IP | Role | Containers |
|------|-----|---------|------|------------|
| Hub | 192.168.1.200 | 100.79.11.3 | Primary server | All above |
| US Outpost | 76.13.107.109 | 100.64.0.1 | Fleet node | sync, node API, Caddy, KSO, SMTP relay |
| Node .246 | 192.168.1.246 | — | Offline | RTX 3070, 32GB RAM, awaiting Docker |
| Node .245 | 192.168.1.245 | — | Offline | RTX 3070, fresh machine |

## DNS (kytranempowerment.com)

- Root (@) → Hostinger CDN (cdn.hstgr.net)
- 27+ subdomains pointing to hub (142.169.21.199)
- 3 subdomains pointing to VPS (76.13.107.109): market, outpost-us, relay
- `news.kytranempowerment.com` is MISSING from DNS
- `creed-ai.org` → Hostinger shared hosting (separate domain)

## Consciousness Module Status

- Embedding loop: ENABLED, runs every 30 min, 200 items/batch
- Analysis loop: ENABLED, runs every 30 min, 10 items/batch, uses mistral:7b
- Translate loop: ENABLED but blocked (no agent has translate skill)
- Loops CANNOT auto-disable (kill switches removed 2026-04-02, Decision #369)
- MCP sessions store to knowledge_base directly (not ai_conversations)

## 4-System Architecture (MANDATORY — See project_core-architecture-vision.md)

1. **Autonomy Module** — runs scheduled jobs (agent_loop.py)
2. **Department HQ** — manages agents, skills, models, departments
3. **AI Bridge + Dispatcher** — routes requests (SHOULD BE MERGED)
4. **Starbase Command** — fleet nodes, extends compute resources

## Before ANY Infrastructure Change

- NEVER touch VPS SSH/keys/passwords without user approval
- NEVER modify docker-compose.yml without warning (triggers rebuild, DNS downtime)
- ALWAYS check if product runs on VPS before making local-only changes
- ALWAYS search KB for existing mistakes before attempting infrastructure
