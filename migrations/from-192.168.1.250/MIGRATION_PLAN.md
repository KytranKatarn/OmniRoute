# Migration Plan: 192.168.1.250 → Archie (192.168.1.200)

**Created**: 2026-01-29
**Source**: 192.168.1.250 (Portainer-managed stacks)
**Destination**: 192.168.1.200 (Archie)

---

## Port Availability Check

All required ports are **FREE** on Archie:

| Port | Stack | Service | Status |
|------|-------|---------|--------|
| 32400 | plex-media-stack | Plex (host mode) | ✓ FREE |
| 8083 | plex-media-stack | SABnzbd | ✓ FREE |
| 8989 | plex-media-stack | Sonarr | ✓ FREE |
| 7878 | plex-media-stack | Radarr | ✓ FREE |
| 9696 | plex-media-stack | Prowlarr | ✓ FREE |
| 5055 | plex-media-stack | Overseerr | ✓ FREE |
| 8123 | home-automation-stack | Home Assistant | ✓ FREE |
| 5354 | network-tools-stack | AdGuard Home | ✓ FREE |
| 3001 | network-tools-stack | ntopng | ✓ FREE |
| 8080 | monitoring-stack | Dozzle | ✓ FREE |
| 8081 | monitoring-stack | cAdvisor | ✓ FREE |
| 8082 | monitoring-stack | Nagios | ✓ FREE |
| 80 | reverse-proxy-stack | Nginx (HTTP) | ✓ FREE |
| 443 | reverse-proxy-stack | Nginx (HTTPS) | ✓ FREE |
| 81 | reverse-proxy-stack | Nginx Admin | ✓ FREE |

---

## Data Migration

### Source Paths (192.168.1.250)

| Stack | Source Path | Size (estimate) |
|-------|-------------|-----------------|
| plex-media-stack | `/mnt/Plex/` | Large (media files) |
| home-automation-stack | `/mnt/HomeLab/homeassistant/` | Small-Medium |
| network-tools-stack | `/mnt/HomeLab/adguard/`, `/mnt/HomeLab/ntopng/` | Small |
| monitoring-stack | `/mnt/HomeLab/nagios/` | Small-Medium |
| reverse-proxy-stack | `./npm/` (relative to compose) | Small |

### Destination Paths (Archie 192.168.1.200)

| Stack | Destination Path |
|-------|------------------|
| plex-media-stack | `/mnt/data/plex/` |
| home-automation-stack | `/mnt/data/homelab/homeassistant/` |
| network-tools-stack | `/mnt/data/homelab/adguard/`, `/mnt/data/homelab/ntopng/` |
| monitoring-stack | `/mnt/data/homelab/nagios/` |
| reverse-proxy-stack | `/mnt/data/homelab/nginx-proxy/` |

---

## Migration Steps

### Phase 1: Prepare Destination (on Archie)

```bash
# Create destination directories
sudo mkdir -p /mnt/data/plex/{config,media,downloads}
sudo mkdir -p /mnt/data/plex/config/{plex,sabnzbd,sonarr,radarr,prowlarr,overseerr}
sudo mkdir -p /mnt/data/plex/media/{movies,tv,music,photos}
sudo mkdir -p /mnt/data/homelab/{homeassistant,adguard,ntopng,nagios,nginx-proxy}
sudo mkdir -p /mnt/data/homelab/adguard/{work,conf}
sudo mkdir -p /mnt/data/homelab/nagios/{config,scripts,data}

# Set ownership (PUID=1000, PGID=1000 matching source)
sudo chown -R 1000:1000 /mnt/data/plex
sudo chown -R 1000:1000 /mnt/data/homelab
```

### Phase 2: Stop Services on Source (192.168.1.250)

```bash
# SSH to source and stop stacks (prevents data corruption during transfer)
ssh kytran@192.168.1.250 "cd /data/compose/3 && docker compose down"   # plex
ssh kytran@192.168.1.250 "cd /data/compose/8 && docker compose down"   # home-automation
ssh kytran@192.168.1.250 "cd /data/compose/9 && docker compose down"   # network-tools
ssh kytran@192.168.1.250 "cd /data/compose/5 && docker compose down"   # monitoring
ssh kytran@192.168.1.250 "cd /data/compose/13 && docker compose down"  # reverse-proxy
```

### Phase 3: Transfer Data (rsync)

Run these commands **from Archie** (pull data from source):

```bash
# 1. Home Assistant (small, do first as test)
rsync -avzP --progress kytran@192.168.1.250:/mnt/HomeLab/homeassistant/ /mnt/data/homelab/homeassistant/

# 2. AdGuard Home
rsync -avzP --progress kytran@192.168.1.250:/mnt/HomeLab/adguard/ /mnt/data/homelab/adguard/

# 3. ntopng
rsync -avzP --progress kytran@192.168.1.250:/mnt/HomeLab/ntopng/ /mnt/data/homelab/ntopng/

# 4. Nagios (monitoring)
rsync -avzP --progress kytran@192.168.1.250:/mnt/HomeLab/nagios/ /mnt/data/homelab/nagios/

# 5. Plex configs (do before media)
rsync -avzP --progress kytran@192.168.1.250:/mnt/Plex/config/ /mnt/data/plex/config/
rsync -avzP --progress kytran@192.168.1.250:/mnt/Plex/downloads/ /mnt/data/plex/downloads/

# 6. Plex media (LARGE - do last, can take hours)
rsync -avzP --progress kytran@192.168.1.250:/mnt/Plex/media/ /mnt/data/plex/media/

# 7. Nginx Proxy Manager (find the actual path first)
# ssh kytran@192.168.1.250 "find /data/compose/13 -name 'npm' -type d"
rsync -avzP --progress kytran@192.168.1.250:/data/compose/13/npm/ /mnt/data/homelab/nginx-proxy/
```

### Phase 4: Deploy Stacks on Archie

```bash
# Navigate to migration compose files
cd /mnt/archie_brain/migrations/from-192.168.1.250/compose

# Deploy in order (dependencies first)
docker compose -f home-automation-stack/docker-compose.yml up -d
docker compose -f network-tools-stack/docker-compose.yml up -d
docker compose -f monitoring-stack/docker-compose.yml up -d
docker compose -f reverse-proxy-stack/docker-compose.yml up -d
docker compose -f plex-media-stack/docker-compose.yml up -d
```

### Phase 5: Verify

1. Check containers running: `docker ps`
2. Test each service:
   - Home Assistant: http://192.168.1.200:8123
   - AdGuard: http://192.168.1.200:5354
   - ntopng: http://192.168.1.200:3001
   - Plex: http://192.168.1.200:32400/web
   - Sonarr: http://192.168.1.200:8989
   - Radarr: http://192.168.1.200:7878
   - Overseerr: http://192.168.1.200:5055
   - Dozzle: http://192.168.1.200:8080
   - Nagios: http://192.168.1.200:8082
   - Nginx Proxy: http://192.168.1.200:81

---

## Rollback Plan

If issues occur:
1. Stop stacks on Archie
2. Restart stacks on source (192.168.1.250)
3. Update DNS/network configs to point back to source

---

## Post-Migration

1. Update DNS records if using hostnames
2. Update any hardcoded IPs in configs (192.168.1.250 → 192.168.1.200)
3. Register stacks in Archie's Docker management (System Operations → Docker tab)
4. Decommission source stacks after verification period (recommend 1 week)
