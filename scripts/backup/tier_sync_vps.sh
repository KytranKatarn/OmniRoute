#!/usr/bin/env bash
# scripts/backup/tier_sync_vps.sh <run_dir>
# Encrypted rsync of smallest-critical components to VPS Outpost over mesh.
# Components synced: database, gitbundles, config (spec §6).
#
# Currently blocked on mesh health — falls back to 'skipped' row in backup_log
# so the sync keeps running rather than dying noisily. Watchdog should alert
# on 'skipped' status for >14 days (Phase 5).
#
# Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md §7
# Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 16

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

: "${BACKUP_VPS_PASSPHRASE:?BACKUP_VPS_PASSPHRASE missing from .env}"
VPS_HOST="${BACKUP_VPS_HOST:-100.64.0.1}"
VPS_USER="${BACKUP_VPS_USER:-kytran}"
VPS_REMOTE_ROOT="${BACKUP_VPS_REMOTE_ROOT:-/var/backups/archie}"

RUN_DIR="${1:?run_dir required}"
VPS_COMPONENTS=(database gitbundles config)

START=$(date +%s)
REMOTE_DIR="${VPS_REMOTE_ROOT}/$(basename "$RUN_DIR")"

# Fast-fail if mesh unreachable.
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" 'echo ok' >/dev/null 2>&1; then
    log_warn "VPS ${VPS_HOST} not reachable — skipping VPS tier"
    log_to_db "vps" "vps" "skipped" "$REMOTE_DIR" "0" "0" "mesh/ssh unreachable"
    exit 0
fi

if ! ssh "${VPS_USER}@${VPS_HOST}" "mkdir -p '${REMOTE_DIR}'" 2>>"$BACKUP_LOG_FILE"; then
    log_error "cannot create remote ${REMOTE_DIR}"
    log_to_db "vps" "vps" "failed" "$REMOTE_DIR" "0" "0" "ssh mkdir failed"
    exit 1
fi

TOTAL=0
FAILED=0
for c in "${VPS_COMPONENTS[@]}"; do
    src="$RUN_DIR/$c"
    [[ ! -d "$src" ]] && continue
    WORK=$(mktemp -d)
    # Encrypt per-file into WORK dir (skip re-encryption if already .enc from config tier).
    for f in "$src"/*; do
        [[ -f "$f" ]] || continue
        out="$WORK/$(basename "$f").enc"
        if [[ "$f" == *.enc ]]; then
            cp "$f" "$out"
        else
            openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
                -in "$f" -out "$out" -pass env:BACKUP_VPS_PASSPHRASE
        fi
    done
    if rsync -az "$WORK/" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/${c}/" 2>>"$BACKUP_LOG_FILE"; then
        sz=$(dir_size_bytes "$WORK")
        TOTAL=$(( TOTAL + sz ))
        log_info "vps tier $c OK ($sz bytes)"
    else
        log_error "vps rsync failed for $c"
        FAILED=1
    fi
    rm -rf "$WORK"
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "vps" "vps" "$STATUS" "$REMOTE_DIR" "$TOTAL" "$DUR"
exit "$FAILED"
