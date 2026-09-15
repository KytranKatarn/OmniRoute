<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate:  docker exec archie_platform python3 \
                    /mnt/archie_brain/scripts/generate_registry_docs.py --services
     Sources: the docker daemon + scripts/deploy_drift_check.py check_products().
     Curated context belongs in the `notes` column. Task #5230 phase 2. -->

# Service Registry

**Collected**: 2026-09-14 18:12:44 EDT · **Provenance measured**: 2026-09-14 03:40:08 EDT

50/52 hub containers running · 9 image-baked products · 0 absent.

> Regenerated from live sources. **`fail_open` is an UNKNOWN, not a fault** —
> the product is unreachable or has no resolvable expected SHA. Do not read it
> as drift. Provenance and collection are timestamped separately because a cheap
> container-only run does not re-measure drift.

## Image-baked products — deploy provenance

| Product | Drift | Baked | Expected | Endpoint |
|---------|-------|-------|----------|----------|
| `civic_watch` | ⚪ fail_open | `unknown` | `0b185eb3b` | http://100.64.0.10:8099/version |
| `gov_watch` | ⚪ fail_open | `unknown` | `7188c02ee` | http://100.64.0.10:8102/version |
| `kbs` | ✅ in_sync | `af99a5421` | `af99a5421` | http://192.168.1.200:8091/version |
| `kso` | ✅ in_sync | `e163d2f46` | `e163d2f46` | http://192.168.1.200:8085/version |
| `legal_watch` | ⚪ fail_open | `unknown` | `4c85b6d15` | http://100.64.0.10:8100/version |
| `market_watch` | ⚪ fail_open | `unknown` | `7b5116ee3` | http://100.64.0.10:8101/version |
| `media_hub` | 🔴 DRIFT | `01d894128` | `9d712c7d3` | http://192.168.1.200:8105/version |
| `wtf_consumer` | ⚪ fail_open | `unknown` | `51a24365c` | http://100.64.0.10:8103/version |
| `wtf_tech` | ⚪ fail_open | `unknown` | `51a24365c` | http://100.64.0.10:8104/version |

## Hub containers

| Container | State | Compose project | Ports | Image |
|-----------|-------|-----------------|-------|-------|
| `archie_browser` | running | archie_brain | — | `archie_brain-archie_browser:latest` |
| `archie_browser_login` | running | archie_brain | 4280->4280/tcp | `archie_brain-archie_browser_login:latest` |
| `archie_codex_terminal` | running | archie_brain | 17682->7681/tcp | `archie_brain-archie_codex_terminal:latest` |
| `archie_comfyui` ⚠ | exited | archie_brain | — | `archie_brain-archie_comfyui:latest` |
| `archie_comms` | running | archie_brain | 3002->3002/tcp | `archie_brain-archie_comms:latest` |
| `archie_database` | running | archie_brain | 5432->5432/tcp | `pgvector/pgvector:pg16` |
| `archie_engine` | running | archie_brain | 9090->9090/tcp | `archie_brain-archie_engine:latest` |
| `archie_headscale` | running | archie_brain | 3478->3478/udp, 8095->8095/tcp | `headscale/headscale:0.25` |
| `archie_llamacpp` | running | archie_brain | — | `ghcr.io/ggml-org/llama.cpp:server` |
| `archie_mcp_gateway` | running | archie_brain | 17800->7800/tcp | `archie_brain-archie_mcp_gateway:latest` |
| `archie_ollama` | running | archie_brain | — | `ollama/ollama:0.6.2` |
| `archie_opencode_terminal` | running | archie_brain | 17685->7681/tcp | `archie_brain-archie_opencode_terminal:latest` |
| `archie_platform` | running | archie_brain | 3000->3000/tcp | `archie_brain-archie_platform:latest` |
| `archie_scheduler` | running | archie_brain | — | `archie_brain-archie_scheduler:latest` |
| `archie_scraper` | running | archie_brain | 4243->4243/tcp | `archie_brain-archie_scraper:latest` |
| `archie_staging` | running | archie_brain | 3003->3000/tcp | `archie_brain-archie_platform:latest` |
| `archie_staging_db` | running | archie_brain | 5433->5432/tcp | `pgvector/pgvector:pg16` |
| `archie_tailscale` | running | archie_brain | — | `tailscale/tailscale:v1.80.3` |
| `archie_whisper` | running | archie_brain | — | `archie_brain-archie_whisper:latest` |
| `omniroute` | running | archie_brain | 20128->20128/tcp | `diegosouzapw/omniroute:3.8.50` |
| `security_nikto` | running | archie_brain | — | `secfigo/nikto:latest` |
| `security_nmap` | running | archie_brain | — | `instrumentisto/nmap:7.94` |
| `security_nuclei` | running | archie_brain | — | `projectdiscovery/nuclei:latest` |
| `security_testssl` | running | archie_brain | — | `drwetter/testssl.sh:3.2` |
| `security_zap` | running | archie_brain | — | `ghcr.io/zaproxy/zaproxy:stable` |
| `kbs_app` | running | kytran-business-suite | 8091->8090/tcp | `kytran-business-suite-kytran-business-suite:` |
| `kbs_postgres` | running | kytran-business-suite | — | `postgres:16-alpine` |
| `kbs_redis` | running | kytran-business-suite | — | `redis:7-alpine` |
| `kbs_worker` | running | kytran-business-suite | — | `kytran-business-suite-kbs-worker:latest` |
| `creed_postgres` | running | kytran-creed | — | `postgres:16-alpine` |
| `kytran_creed` | running | kytran-creed | 8086->8086/tcp | `kytran-creed-creed:latest` |
| `kytran-sysops-postgres` | running | kytran-server-manager | — | `postgres:16-alpine` |
| `kytran-system-operations` | running | kytran-server-manager | 8085->8085/tcp | `kytran-server-manager-kytran-system-operatio` |
| `media_jellyfin` | running | media-stack | 8096->8096/tcp | `jellyfin/jellyfin:10.11` |
| `media_overseerr` | running | media-stack | 5055->5055/tcp | `lscr.io/linuxserver/overseerr:1.35.0` |
| `media_plex` | running | media-stack | — | `lscr.io/linuxserver/plex:1.43.0` |
| `media_prowlarr` | running | media-stack | 9696->9696/tcp | `lscr.io/linuxserver/prowlarr:2.3.5` |
| `media_radarr` | running | media-stack | 7878->7878/tcp | `lscr.io/linuxserver/radarr:6.1.1` |
| `media_sabnzbd` | running | media-stack | 8083->8080/tcp | `lscr.io/linuxserver/sabnzbd:4.5.5` |
| `media_samba` ⚠ | exited | media-stack | — | `dperson/samba:latest` |
| `media_sonarr` | running | media-stack | 8989->8989/tcp | `lscr.io/linuxserver/sonarr:4.0.17` |
| `mediahub_app` | running | media_hub | 8105->8105/tcp | `mediahub:standalone` |
| `mediahub_db` | running | media_hub | — | `postgres:16.4-alpine` |
| `monitoring_cadvisor` | running | network-tools | 8081->8080/tcp | `gcr.io/cadvisor/cadvisor:v0.51.0` |
| `monitoring_dozzle` | running | network-tools | 8080->8080/tcp | `amir20/dozzle:v8-pinned` |
| `monitoring_nagios` | running | network-tools | 8082->80/tcp | `jasonrivers/nagios:4.5.7` |
| `network_adguard` | running | network-tools | — | `adguard/adguardhome:v0.108.0-b.84` |
| `network_ntopng` | running | network-tools | — | `ntop/ntopng:v6-pinned` |
| `network_redis` | running | network-tools | 6379->6379/tcp | `redis:7-alpine` |
| `stalwart_mail` | running | stalwart-mail | 25->25/tcp, 4190->4190/tcp, 465->465/tcp, 587->587/tcp, 8443->443/tcp, 993->993/tcp | `stalwartlabs/mail-server:v0.11.8` |
| `tdarr` | running | tdarr | 8265->8265/tcp, 8266->8266/tcp | `ghcr.io/haveagitgat/tdarr:latest` |
| `archie_hub_caddy` | running | (bare docker run) | — | `caddy:2-alpine` |


---

*Phase 2 of the Living Platform Registry (#5230). Add curated context with `platform_registry_service.set_service_notes(key, text)` — never by editing this file.*
