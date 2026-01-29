#!/bin/bash
# Migration script: 192.168.1.250 → Archie (192.168.1.200)
# Run this script ON ARCHIE to pull data from source

set -e

SOURCE="kytran@192.168.1.250"
RSYNC_OPTS="-avzP --progress"

echo "=============================================="
echo "  Stack Migration: 192.168.1.250 → Archie"
echo "=============================================="
echo ""

# Phase 1: Create directories
echo "[Phase 1] Creating destination directories..."
sudo mkdir -p /mnt/data/plex/{config,media,downloads}
sudo mkdir -p /mnt/data/plex/config/{plex,sabnzbd,sonarr,radarr,prowlarr,overseerr}
sudo mkdir -p /mnt/data/plex/media/{movies,tv,music,photos}
sudo mkdir -p /mnt/data/homelab/{homeassistant,adguard,ntopng,nagios,nginx-proxy}
sudo mkdir -p /mnt/data/homelab/adguard/{work,conf}
sudo mkdir -p /mnt/data/homelab/nagios/{config,scripts,data}
sudo mkdir -p /mnt/data/homelab/nginx-proxy/{data,letsencrypt}

sudo chown -R 1000:1000 /mnt/data/plex
sudo chown -R 1000:1000 /mnt/data/homelab
echo "✓ Directories created"
echo ""

# Phase 2: Migrate small stacks first
echo "[Phase 2] Migrating Home Assistant..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/HomeLab/homeassistant/ /mnt/data/homelab/homeassistant/
echo "✓ Home Assistant migrated"
echo ""

echo "[Phase 3] Migrating AdGuard Home..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/HomeLab/adguard/ /mnt/data/homelab/adguard/
echo "✓ AdGuard migrated"
echo ""

echo "[Phase 4] Migrating ntopng..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/HomeLab/ntopng/ /mnt/data/homelab/ntopng/
echo "✓ ntopng migrated"
echo ""

echo "[Phase 5] Migrating Nagios..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/HomeLab/nagios/ /mnt/data/homelab/nagios/
echo "✓ Nagios migrated"
echo ""

echo "[Phase 6] Migrating Nginx Proxy Manager..."
rsync $RSYNC_OPTS ${SOURCE}:/data/compose/13/npm/ /mnt/data/homelab/nginx-proxy/ 2>/dev/null || echo "  (NPM data not found at expected path, may need manual copy)"
echo ""

echo "[Phase 7] Migrating Plex configs..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/Plex/config/ /mnt/data/plex/config/
echo "✓ Plex configs migrated"
echo ""

echo "[Phase 8] Migrating Plex downloads..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/Plex/downloads/ /mnt/data/plex/downloads/
echo "✓ Plex downloads migrated"
echo ""

echo "[Phase 9] Migrating Plex media (this may take a while)..."
rsync $RSYNC_OPTS ${SOURCE}:/mnt/Plex/media/ /mnt/data/plex/media/
echo "✓ Plex media migrated"
echo ""

echo "=============================================="
echo "  Data Migration Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "  1. Deploy stacks:  ./deploy_stacks.sh"
echo "  2. Register in DB: python3 register_stacks.py"
echo "  3. Verify services are running"
