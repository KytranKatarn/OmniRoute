#!/usr/bin/env bash
# deploy.sh — deploy WTF to Citadel/boston-2 (root@100.64.0.10) — migrated off outpost-us 2026-06 (#4032)
# Usage: ./deploy.sh [service]
#   service: consumer | ingest | ingest-api | tech | all (default: all)
#            (the full compose names wtf-consumer / wtf-ingest / wtf-ingest-api /
#             wtf-tech are accepted too — both spellings work)
#
# The short names above are now REAL. Until 2026-08-19 this header advertised
# `consumer | ingest | tech` while the code passed the argument straight to
# `docker compose`, whose services are all `wtf-` prefixed — so every documented
# single-service invocation failed with "no such service", and it failed AFTER
# the rsync, leaving the VPS source ahead of its running container.
# This script wraps the canonical rsync + docker compose up --build pattern.
# NEVER deploy to /opt/archie-products/wtf/ — that dir is a stale duplicate.

set -euo pipefail

VPS="root@100.64.0.10"
KEY="$HOME/.ssh/id_ed25519"
VPS_DIR="/opt/archie-products/what-the-fact"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE="${1:-all}"

# Services are read from docker-compose.yml, never hardcoded: `all` used to be a
# hand-written list of THREE while the file defined FOUR, so wtf-ingest-api was
# silently left on stale code by a command whose whole promise is "everything".
ALL_SERVICES="$(awk '/^services:/{s=1;next} /^[^[:space:]]/{s=0} s && /^  [a-z0-9_-]+:/{gsub(/[ :]/,"");print}' "$(dirname "$0")/docker-compose.yml")"

if [ "$SERVICE" != "all" ]; then
  # Accept the short form (consumer) as well as the compose name (wtf-consumer).
  case "$SERVICE" in
    wtf-*) RESOLVED="$SERVICE" ;;
    *)     RESOLVED="wtf-$SERVICE" ;;
  esac
  if ! printf '%s\n' $ALL_SERVICES | grep -qx "$RESOLVED"; then
    echo "ERROR: unknown service '$SERVICE' (resolved to '$RESOLVED')." >&2
    echo "       docker-compose.yml defines:" >&2
    printf '         %s\n' $ALL_SERVICES >&2
    echo "       Nothing was rsynced — the VPS is untouched." >&2
    exit 2
  fi
  SERVICE="$RESOLVED"
fi

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
  TARGETS="$(printf '%s ' $ALL_SERVICES)"
else
  TARGETS="$SERVICE"
fi
echo "      targets: $TARGETS"
ssh -i "$KEY" "$VPS" \
  "cd $VPS_DIR && GIT_SHA=$GIT_SHA BUILD_TIME=$BUILD_TIME docker compose up -d --build $TARGETS"

echo "      ✓ Containers rebuilt"

# Step 3: Verify
echo "[3/3] Verifying..."
sleep 3
ssh -i "$KEY" "$VPS" "docker ps --format '{{.Names}} | {{.Status}}' | grep what-the-fact"

echo ""
echo "==> Deploy complete. Check logs with:"
echo "    ssh -i $KEY $VPS 'docker logs --tail=30 what-the-fact-wtf-ingest-1'"
