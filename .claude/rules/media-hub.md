# Media Hub Rules

**Two separate things share this name** — read carefully:

| Thing | What it is |
|-------|-----------|
| **Media Hub (standalone)** | Port 8105, `media.kytranempowerment.com`, own Docker container `mediahub_app`, own DB |
| **Media Hub (platform module)** | `/tools/media-hub` in `platform_v2/` — wrapper that links to the standalone |

These rules cover **both**. The standalone is live; the platform module is a launch link.

## Standalone — media.kytranempowerment.com (:8105)

- Source: `/mnt/archie_brain/standalone/media_hub/`
- Container: `mediahub_app` on hub (NOT VPS)
- Live since: 2026-04-19
- DB: Own PostgreSQL DB (NOT the main `archie` DB)

### Services Integrated

| Service | Purpose |
|---------|---------|
| **Plex** | Primary media server (port 32400 host) |
| **Jellyfin** | Secondary/migration target (:8096) |
| **Overseerr** | User media requests (:5055) |
| **Sonarr** | TV series management (:8989) |
| **Radarr** | Movie management (:7878) |
| **Prowlarr** | Indexer management (:9696) |
| **SABnzbd** | Download client (:8083) |
| **TMDB** | Metadata enrichment with LRU cache |

### M.A.V.E.N. Probes (standalone health checks)

| Probe | Interval |
|-------|---------|
| `grab_notify` | 5 min |
| `download_pipeline` | 30 min |
| `download_client_health` | 30 min |
| `library_coverage` | 2 hr |
| `arr_database` | 30 min |
| `stale_queue` | 30 min |

### DB Tables

| Table | Purpose |
|-------|---------|
| `media_hub_services` | Service credential + config store |
| `media_hub_requests` | User media request queue |
| `media_library_cache` | TTL-cached library data |

### Key Gotchas

- **SABnzbd `set_config` is unreliable** — edit `sabnzbd.ini` directly (KB #261306)
- **Stale Sonarr download queue** — purge SABnzbd history too, not just Sonarr queue (KB #261307)
- **Stalwart SMTP from container**: `http://stalwart_mail:8080` NEVER `https://mail.kytranempowerment.com`
- **Docker DNS override REQUIRED**: add `dns: [192.168.1.200, 1.1.1.1]` to `mediahub_app` service — Hub's `/etc/resolv.conf` is Tailscale-owned, Docker embedded resolver drops fallback (KB standalone-extraction.md #10)
- Media requests go to Overseerr (human approval), then Sonarr/Radarr, then SABnzbd
- M.A.V.E.N. (#?) is the standalone's health agent — dispatches via DHQ for analysis

## Platform Module — `/tools/media-hub`

- Blueprint: `media_hub_bp` | Route: `/tools/media-hub` | Category: `applications_concepts`
- Status: Acts as a launch tile → redirects to `media.kytranempowerment.com`
- Routes: 25+ routes for ARCHIE integration, Overseerr request proxying, TMDB search

### Platform DB Tables

| Table | Purpose |
|-------|---------|
| `media_hub_services` | Shared with standalone — service credentials |
| `media_hub_requests` | Request queue |

## Deploy Pattern (standalone)

```bash
# Hub-local container — use docker compose, NOT rsync (it's on hub not VPS)
cd /mnt/archie_brain/standalone/media_hub/
docker compose up -d --build mediahub_app
docker compose restart mediahub_app  # for volume-mounted config changes only
```
