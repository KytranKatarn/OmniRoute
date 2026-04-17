#!/usr/bin/env bash
# scripts/backup/component_vps_pull.sh <run_dir>
# Weekly rsync of VPS product DBs + persistence dirs from US Outpost over mesh.
#
# PRE-REQ: SSH key deployed for kytran@<mesh-ip>. As of 2026-04-16, mesh is
# unreachable from the hub (Headscale not up) — this script will fail cleanly
# and log it. Phase 5 watchdog should alert if vps tier status stays 'skipped'
# for >14 days.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/vps_pull"
mkdir -p "$OUT_DIR"

VPS_HOST="${BACKUP_VPS_HOST:-100.64.0.1}"
VPS_USER="${BACKUP_VPS_USER:-kytran}"

START=$(date +%s)

# Fast-fail if mesh is unreachable — avoid 10-min rsync timeout.
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" 'echo ok' >/dev/null 2>&1; then
    log_warn "VPS ${VPS_HOST} not reachable — skipping vps_pull"
    log_to_db "vps_pull" "primary" "skipped" "" "0" "0" "mesh/ssh unreachable"
    exit 0
fi

FAILED=0
VPS_DBS=(market_watch civic_watch legal_watch gov_watch thenews)
for db in "${VPS_DBS[@]}"; do
    remote_path="/tmp/${db}_$(date +%Y%m%d).dump"
    if ssh "${VPS_USER}@${VPS_HOST}" "docker exec ${db}_db pg_dump -U postgres -d ${db} -Fc -Z 6 > ${remote_path}" 2>>"$BACKUP_LOG_FILE"; then
        rsync -az "${VPS_USER}@${VPS_HOST}:${remote_path}" "$OUT_DIR/" 2>>"$BACKUP_LOG_FILE" \
            && ssh "${VPS_USER}@${VPS_HOST}" "rm -f ${remote_path}" || true
    else
        log_warn "VPS DB dump failed for $db (container may not exist) — skipping"
    fi
done

# Pull each product's persistence dir.
ssh "${VPS_USER}@${VPS_HOST}" 'ls -d /root/*/persistence 2>/dev/null || true' | while read -r rp; do
    [[ -z "$rp" ]] && continue
    name=$(echo "$rp" | awk -F/ '{print $(NF-1)}')
    rsync -az "${VPS_USER}@${VPS_HOST}:${rp}" "$OUT_DIR/${name}_persistence" 2>>"$BACKUP_LOG_FILE" || FAILED=1
done

SIZE=$(dir_size_bytes "$OUT_DIR")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_info "vps_pull $STATUS — $SIZE bytes in ${DUR}ms"
log_to_db "vps_pull" "primary" "$STATUS" "$OUT_DIR" "$SIZE" "$DUR"
exit "$FAILED"
