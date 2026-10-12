# Operational State — DO NOT SKIP

*Condensed 2026-10-12 (task 7179): DR-quorum and DNS correction narratives shortened. Full previous text: `git show b3bd529dc:.claude/rules/operational-state.md`.*

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
| Starship - Defiant - USS-246 | 192.168.1.246 | 100.64.0.3 | **Online** (verified 2026-09-08) | RTX 3070, 32GB RAM. SSH `Famil@`. ⚠️ **WINDOWS** — no bash/python3, so it cannot run `probe_hub.sh`. ✅ It IS a DR quorum vantage since PR #3253 (2026-09-08): annotated `Famil@100.64.0.3|pwsh` in `OUTPOSTS`, driven through **`probe_hub.ps1`**. Verified live voting `up` vs the hub and `down` vs TEST-NET. |
| Starship - Runabout - USS-245 | 192.168.1.245 | 100.64.0.6 | **Online** (verified 2026-09-08) | RTX 3050 4GB, 12GB RAM. SSH `Famil@`. ⚠️ **WINDOWS** — same as USS-246: `probe_hub.sh` will not run, `probe_hub.ps1` does. Voting vantage `Famil@100.64.0.6|pwsh` since PR #3253. |

## DR quorum vantages (2026-09-08, PR #3253)

`OUTPOSTS` in `scripts/dr/watchdog/dr_watchdog.sh` — **3 vantages, `QUORUM=2`**:

| vantage | shell | probe |
|---|---|---|
| `kytran@100.64.0.2` (outpost-us) | bash | `probe_hub.sh` |
| `Famil@100.64.0.3\|pwsh` (USS-246) | PowerShell | `probe_hub.ps1` |
| `Famil@100.64.0.6\|pwsh` (USS-245) | PowerShell | `probe_hub.ps1` |

🔴 **A vantage votes ONLY on the stdout sentinel `PROBE_RESULT=up|down`.** Anything else — including a non-zero exit with no sentinel — is `unreachable` and IGNORED by `count_down`. Never re-derive the vote from an exit code: PowerShell's `exit 1` over `ssh "powershell -NoProfile -Command -"` arrives as exit 0, and the old "non-255 means down" rule made both Starships vote `down` against a verifiably UP hub (phantom votes that would auto-promote on the first mesh hiccup).

⚠️ The majority is PARTLY CORRELATED (accepted trade): two of three vantages sit on the hub's own LAN, so a LAN-wide fault can yield two real down-votes for a hub that is fine from the internet; outpost-us is the only remote vantage left after the 2026-08-29 sunset. **A new vantage is not done until its probe is verified live** — one that cannot emit the sentinel silently degrades to a non-voter.

## DNS (kytranempowerment.com)

_(Audited + pruned 2026-06-11 — KB #272182. Verify public DNS from an EXTERNAL resolver: the hub's AdGuard split-horizon resolves many names to 192.168.1.200 locally.)_

- Root (@) + `www` → Hostinger CDN (cdn.hstgr.net); `creed-ai.org` → Hostinger shared hosting.
- **Citadel (2.25.133.122) fronts the hub's services as a CONTAINER named `beacon`** (caddy:2-alpine; config on the HOST at `/opt/archie-ingress/Caddyfile`, bind-mounted to `/etc/caddy/Caddyfile`): platform, consciousness, business, creed, mediahub, media, jellyfin, plex, adguard, nagios, server, store, archie, bridge, claude, codex, terminal, sandbox, shop, mesh. The original Beacon VPS (2.25.170.252) was removed by Hostinger 2026-08-28; DR scripts that ssh'd to it could not move public traffic (#3245/#3248). Verify with `docker ps --filter name=^beacon$` **on Citadel**.
- **Citadel products** (`archie_ingress_caddy` → local containers at 172.18.0.1:<port>): gov, market, legal, civic, wtf, mta-sts, voice (reserved, no service); `what-the-fact.com`/`.tech` apexes also resolve here.
- ⚠️ **`mail.` is HUB-fronted (192.168.1.200), NOT Citadel** — settled by probing (hub 25/587/993 open, Citadel 25/993 closed); `mta-sts` is the one on Citadel (static policy host). A wrong "mail is on Citadel" line once got `mail.` repointed during the #5219 recovery (KB #284817). `scripts/dr/adguard_flip.sh` leaves `mail.` OUT of its target map deliberately — do not add it back without re-probing.
- **outpost-us (76.13.107.109)** = `api`, `relay`, `outpost-us` only (api→hub mesh, SMTP relay, socks, sync, node_api). NO product stacks.
- Mail: SPF `v=spf1 a mx ip4:76.13.107.109 -all`, DMARC `p=reject`, `_mta-sts` (policy served, **mode=testing**; enforce gated on the relay cert, task #4044), `_smtp._tls`, DKIM `stalwart`+`default`, MX `10 mail` / `20 relay`.
- Old hub public IP **153.68.195.85 is STALE** (the hub is now a dynamic residential IP); external traffic enters via Citadel's `beacon` container. **NPM was decommissioned 2026-06-27** (ADR-853, PR #1953/#1954/#1956): the hub has no :80/:443 listener and `npm_service.py` is gone. Rollback = restore the compose block + `AdGuardHome.yaml.bak`. STILL OPEN (owner, via the AdGuard UI, never by text-editing the YAML): 2 stale rewrites `proxy.*`, `brainstorm.*` (KB #276163).
- Stale records (`thenews`, `n8n`, `fdtest`, `ftp`, `webmail`, `mail-admin`, `brainstorm`, `proxy`, legacy `zmail._domainkey`) were pruned 2026-06-11 (#4032), all NXDOMAIN.

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
