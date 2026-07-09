#!/usr/bin/env bash
# deploy.sh — deploy WTF to Citadel/boston-2 (root@100.64.0.10) — migrated off outpost-us 2026-06 (#4032)
# Usage: ./deploy.sh [service]
#   service: consumer | ingest | tech | all (default: all)
# This script wraps the canonical rsync + docker compose up --build pattern.
# NEVER deploy to /opt/archie-products/wtf/ — that dir is a stale duplicate.

set -euo pipefail

VPS="root@100.64.0.10"
KEY="$HOME/.ssh/id_ed25519"
VPS_DIR="/opt/archie-products/what-the-fact"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE="${1:-all}"

# Deploy-provenance (#4776): stamp the built image with the archie-platform commit so
# /version reports it and the fleet drift monitor can compare against the repo head.
# Forwarded into the remote `docker compose build` env → picked up by build.args.
GIT_SHA="$(git -C "$LOCAL_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "==> WTF Deploy — service: $SERVICE (git_sha ${GIT_SHA:0:12})"
echo "==> Source: $LOCAL_DIR"
echo "==> Target: $VPS:$VPS_DIR"
echo ""

# Step 1: Rsync (always exclude .env — VPS has live secrets)
echo "[1/3] Rsyncing code to VPS..."
rsync -az --delete \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  --exclude='*.log' \
  -e "ssh -i $KEY" \
  "$LOCAL_DIR/" \
  "$VPS:$VPS_DIR/"

echo "      ✓ Rsync complete"

# Step 2: Rebuild + restart containers
echo "[2/3] Rebuilding containers on VPS..."
if [ "$SERVICE" = "all" ]; then
  ssh -i "$KEY" "$VPS" \
    "cd $VPS_DIR && GIT_SHA=$GIT_SHA BUILD_TIME=$BUILD_TIME docker compose up -d --build wtf-consumer wtf-ingest wtf-tech"
else
  ssh -i "$KEY" "$VPS" \
    "cd $VPS_DIR && GIT_SHA=$GIT_SHA BUILD_TIME=$BUILD_TIME docker compose up -d --build $SERVICE"
fi

echo "      ✓ Containers rebuilt"

# Step 3: Verify
echo "[3/3] Verifying..."
sleep 3
ssh -i "$KEY" "$VPS" "docker ps --format '{{.Names}} | {{.Status}}' | grep what-the-fact"

echo ""
echo "==> Deploy complete. Check logs with:"
echo "    ssh -i $KEY $VPS 'docker logs --tail=30 what-the-fact-wtf-ingest-1'"
