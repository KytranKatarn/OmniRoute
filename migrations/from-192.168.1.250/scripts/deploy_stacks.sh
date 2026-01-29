#!/bin/bash
# Deploy migrated stacks on Archie
# Run AFTER migrate_data.sh

set -e

COMPOSE_DIR="/mnt/archie_brain/migrations/from-192.168.1.250/compose"

echo "=============================================="
echo "  Deploying Migrated Stacks"
echo "=============================================="
echo ""

# Deploy in order (least dependencies first)
echo "[1/5] Deploying Home Assistant..."
docker compose -f ${COMPOSE_DIR}/home-automation-stack/docker-compose.yml up -d
echo "✓ Home Assistant deployed"
echo ""

echo "[2/5] Deploying Network Tools (AdGuard, ntopng)..."
docker compose -f ${COMPOSE_DIR}/network-tools-stack/docker-compose.yml up -d
echo "✓ Network Tools deployed"
echo ""

echo "[3/5] Deploying Monitoring (Dozzle, cAdvisor, Nagios)..."
docker compose -f ${COMPOSE_DIR}/monitoring-stack/docker-compose.yml up -d
echo "✓ Monitoring deployed"
echo ""

echo "[4/5] Deploying Reverse Proxy (Nginx Proxy Manager)..."
docker compose -f ${COMPOSE_DIR}/reverse-proxy-stack/docker-compose.yml up -d
echo "✓ Reverse Proxy deployed"
echo ""

echo "[5/5] Deploying Plex Media Stack..."
docker compose -f ${COMPOSE_DIR}/plex-media-stack/docker-compose.yml up -d
echo "✓ Plex Media Stack deployed"
echo ""

echo "=============================================="
echo "  Deployment Complete!"
echo "=============================================="
echo ""
echo "Verifying containers..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -20
echo ""
echo "Service URLs:"
echo "  - Home Assistant:  http://192.168.1.200:8123"
echo "  - AdGuard Home:    http://192.168.1.200:5354"
echo "  - ntopng:          http://192.168.1.200:3001"
echo "  - Plex:            http://192.168.1.200:32400/web"
echo "  - Sonarr:          http://192.168.1.200:8989"
echo "  - Radarr:          http://192.168.1.200:7878"
echo "  - Prowlarr:        http://192.168.1.200:9696"
echo "  - Overseerr:       http://192.168.1.200:5055"
echo "  - SABnzbd:         http://192.168.1.200:8083"
echo "  - Dozzle:          http://192.168.1.200:8080"
echo "  - cAdvisor:        http://192.168.1.200:8081"
echo "  - Nagios:          http://192.168.1.200:8082"
echo "  - Nginx Proxy:     http://192.168.1.200:81"
echo ""
echo "Next: Run 'python3 register_stacks.py' to add to Archie's Docker tab"
