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
VPS_USER="${BACKUP_VPS_USER:-kytran}"
# Default to user home — kytran can't write to /var/backups on a stock Ubuntu.
# Override via BACKUP_VPS_REMOTE_ROOT in .env if the VPS admin has created
# /var/backups/archie with kytran:kytran ownership.
VPS_REMOTE_ROOT="${BACKUP_VPS_REMOTE_ROOT:-/home/kytran/backups/archie}"

# Host preference: try mesh first (faster, avoids public SSH hits), fall back
# to public IP when mesh is dark. BACKUP_VPS_HOST in .env forces a specific
# host (useful when debugging).
if [[ -n "${BACKUP_VPS_HOST:-}" ]]; then
    VPS_HOSTS=( "$BACKUP_VPS_HOST" )
else
    VPS_HOSTS=( "100.64.0.2" "76.13.107.109" )
fi

RUN_DIR="${1:?run_dir required}"
VPS_COMPONENTS=(database gitbundles config)

START=$(date +%s)

# Pick first reachable host.
VPS_HOST=""
for candidate in "${VPS_HOSTS[@]}"; do
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "${VPS_USER}@${candidate}" 'exit 0' 2>/dev/null; then
        VPS_HOST="$candidate"
        log_info "VPS tier using ${VPS_HOST}"
        break
    fi
done

REMOTE_DIR="${VPS_REMOTE_ROOT}/$(basename "$RUN_DIR")"

# Fast-fail if no host reachable.
if [[ -z "$VPS_HOST" ]]; then
    log_warn "VPS unreachable on all candidates (${VPS_HOSTS[*]}) — skipping VPS tier"
    log_to_db "vps" "vps" "skipped" "$REMOTE_DIR" "0" "0" "no reachable host"
    exit 0
fi

if ! ssh "${VPS_USER}@${VPS_HOST}" "mkdir -p '${REMOTE_DIR}'" 2>>"$BACKUP_LOG_FILE"; then
    log_error "cannot create remote ${REMOTE_DIR}"
    log_to_db "vps" "vps" "failed" "$REMOTE_DIR" "0" "0" "ssh mkdir failed"
    exit 1
fi

# #5847: stage encrypted copies on DISK, never in /tmp. /tmp is a 2.0G tmpfs and the
# encrypted database dump alone is ~1.9G, so `mktemp -d` there CANNOT hold it -- openssl
# died mid-write, `set -e` killed the script before the `rm -rf "$WORK"` below, and the
# orphaned 1.9G artifact then kept /tmp full so every later run failed identically.
# Two nights lost (2026-08-19/20) and it took the hub's Docker runtime down with it.
# BACKUP_ROOT is /mnt/data2/backups. Mirrors tier_sync_gdrive.py's staging pattern.
STAGE=$(mktemp -d "${BACKUP_ROOT}/.vps_sync.XXXXXX")
# The `rm -rf` at the end of the loop only runs on the happy path. This trap is what
# makes an orphan impossible when the script dies mid-encrypt.
trap 'rm -rf "$STAGE"' EXIT

TOTAL=0
FAILED=0
for c in "${VPS_COMPONENTS[@]}"; do
    src="$RUN_DIR/$c"
    [[ ! -d "$src" ]] && continue
    WORK=$(mktemp -d "${STAGE}/${c}.XXXXXX")
    # Encrypt per-file into WORK dir (skip re-encryption if already .enc from config tier).
    enc_ok=1
    for f in "$src"/*; do
        [[ -f "$f" ]] || continue
        out="$WORK/$(basename "$f").enc"
        # #5847: guard BOTH copy and encrypt. Unguarded under `set -e` these killed the
        # whole script UPSTREAM of log_to_db, so a two-night off-site outage left ZERO
        # rows in backup_log -- unmonitored while appearing monitored. Record instead.
        if [[ "$f" == *.enc ]]; then
            cp "$f" "$out" || enc_ok=0
        else
            openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
                -in "$f" -out "$out" -pass env:BACKUP_VPS_PASSPHRASE || enc_ok=0
        fi
        if [[ $enc_ok -eq 0 ]]; then
            log_error "vps encrypt/copy failed for $(basename "$f") ($c)"
            FAIL_REASONS="${FAIL_REASONS:+$FAIL_REASONS; }${c}: encrypt failed for $(basename "$f")"
            FAILED=1
            break
        fi
    done
    # #5619: capture rsync's OWN stderr rather than only redirecting it to the log
    # file. The summary row below used to omit log_to_db's 7th argument entirely, so
    # every failed vps run wrote error_message=NULL. On 2026-08-15 six consecutive
    # nightly failures said only "failed" while the real cause — outpost-us root disk
    # at 100%, which let the 20 MB gitbundles through and rejected the 1.8 GB dump —
    # existed nowhere in the DB. Diagnosing it needed a human grepping an 11 MB host
    # log. rsync says "No space left on device"; record that.
    if [[ $enc_ok -eq 0 ]]; then
        # #5847: never ship a partial component set. A truncated upload that reports OK
        # is a restore point that does not exist.
        log_error "vps skipping rsync for $c -- encryption incomplete"
        rm -rf "$WORK"
        continue
    fi
    if rsync_out=$(rsync -az "$WORK/" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/${c}/" 2>&1); then
        sz=$(dir_size_bytes "$WORK")
        TOTAL=$(( TOTAL + sz ))
        log_info "vps tier $c OK ($sz bytes)"
    else
        log_error "vps rsync failed for $c"
        printf '%s\n' "$rsync_out" >> "$BACKUP_LOG_FILE"
        # Keep the LAST stderr line (rsync puts the actual reason there) and bound it,
        # so one pathological error can't bloat the row or the alert body.
        _why=$(printf '%s' "$rsync_out" | tail -1 | cut -c1-120)
        FAIL_REASONS="${FAIL_REASONS:+$FAIL_REASONS; }${c}: ${_why:-rsync failed with no stderr}"
        FAILED=1
    fi
    rm -rf "$WORK"
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
# Arg 7 is log_to_db's `err` -> backup_log.error_message. Omitting it (the pre-#5619
# behaviour) is what made every vps failure unreadable from the DB.
log_to_db "vps" "vps" "$STATUS" "$REMOTE_DIR" "$TOTAL" "$DUR" "${FAIL_REASONS:-}"
exit "$FAILED"
