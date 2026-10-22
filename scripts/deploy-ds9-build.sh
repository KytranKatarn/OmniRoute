#!/usr/bin/env bash
# Deploy a built DS9 gateway artifact, keeping the old one for rollback.
#
# Usage: scripts/deploy-ds9-build.sh <built-dir-name>
#   e.g. scripts/deploy-ds9-build.sh next-aihorde
#
# WHY A SCRIPT AND NOT A HAND-ROLLED SWAP
# ---------------------------------------
# The gateway runs from .build/next/standalone (systemd WorkingDirectory), so a
# swap is two directory renames plus a restart. Done by hand, the failure modes
# are: swapping while the service still holds the old directory open, losing the
# rollback artifact, and restarting before the new artifact is complete. This
# script refuses to swap an INCOMPLETE build (no server.js), keeps the old
# artifact, and verifies the new one before the service is told to use it.
#
# ROLLBACK: the previous artifact is left at .build/next-pre-<name>-<ts>.
# To roll back: stop the service, move the current .build/next aside, move the
# rollback artifact back to .build/next, start the service.

set -euo pipefail

BUILD_NAME="${1:?usage: deploy-ds9-build.sh <built-dir-name>}"
ROOT="/mnt/standalone/deep-space-9"
BUILDS="$ROOT/.build"
SRC="$BUILDS/$BUILD_NAME"
LIVE="$BUILDS/next"
SERVICE="deep-space-9.service"

cd "$ROOT"

echo "==> pre-flight"
[ -d "$SRC" ] || { echo "FATAL: $SRC does not exist"; exit 1; }
[ -f "$SRC/standalone/server.js" ] || { echo "FATAL: $SRC/standalone/server.js is missing - the build is INCOMPLETE, refusing to swap"; exit 1; }
[ -d "$LIVE" ] || { echo "FATAL: $LIVE does not exist"; exit 1; }
echo "    new artifact : $SRC ($(du -sh "$SRC" | cut -f1))"
echo "    live artifact: $LIVE ($(du -sh "$LIVE" | cut -f1))"

echo "==> the change must be IN the artifact"
# The aihorde executor is registered by id, so its presence in the built server
# bundle is the check that the artifact actually contains it.
if grep -rq "oai.aihorde.net" "$SRC/standalone" 2>/dev/null; then
  echo "    aihorde executor: PRESENT"
else
  echo "    aihorde executor: NOT FOUND in the artifact - refusing to swap"
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
ROLLBACK="$BUILDS/next-pre-${BUILD_NAME}-${TS}"

echo "==> stopping the gateway"
sudo -n systemctl stop "$SERVICE"

echo "==> swapping (old artifact kept for rollback)"
mv "$LIVE" "$ROLLBACK"
mv "$SRC" "$LIVE"
echo "    live  -> $LIVE"
echo "    rollback -> $ROLLBACK"

echo "==> starting the gateway"
sudo -n systemctl start "$SERVICE"

echo "==> waiting for health"
for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:20129/api/health || echo 000)
  if [ "$code" = "200" ]; then echo "    healthy after $((i * 5))s"; break; fi
  sleep 5
done
[ "${code:-000}" = "200" ] || { echo "FATAL: the gateway did not come back healthy (last HTTP $code)"; echo "        rollback artifact: $ROLLBACK"; exit 1; }

echo "==> done"
echo "    live artifact : $LIVE"
echo "    rollback      : $ROLLBACK"
