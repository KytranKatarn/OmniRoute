#!/usr/bin/env bash
# Smoke test for VPS backup tier connectivity.
# Tries mesh IP first, falls back to public IP. Reports which worked.
set -u

MESH_IP="${MESH_IP:-100.64.0.1}"
PUB_IP="${PUB_IP:-76.13.107.109}"
VPS_USER="${VPS_USER:-kytran}"
REMOTE_DIR="${VPS_BACKUP_DIR:-/var/backups/archie}"

check() {
    local host="$1" label="$2"
    if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
        "${VPS_USER}@${host}" "mkdir -p ${REMOTE_DIR} && echo ok" 2>&1 | tail -1 | grep -q '^ok$'; then
        echo "OK ${label} (${host}): reachable, ${REMOTE_DIR} writable"
        return 0
    fi
    echo "FAIL ${label} (${host}): unreachable or ${REMOTE_DIR} not writable"
    return 1
}

check "$MESH_IP" "mesh" && exit 0
check "$PUB_IP"  "public" && exit 0
echo "Both paths failed — check Headscale + SSH key."
exit 1
