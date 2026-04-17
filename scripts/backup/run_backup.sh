#!/usr/bin/env bash
# scripts/backup/run_backup.sh
# Top-level backup orchestrator. Called from cron.
#
# Usage:
#   run_backup.sh daily
#   run_backup.sh weekly
#   run_backup.sh monthly
#   run_backup.sh <component>   # e.g. db, code, gitbundle, config
#
# Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md
# Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 3

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

MODE="${1:-daily}"
TS=$(backup_ts)
RUN_DIR="${BACKUP_ROOT}/${TS}_${MODE}"

mkdir -p "$BACKUP_ROOT"
acquire_lock "$MODE" || { log_error "run_backup $MODE aborted — locked"; exit 2; }

log_info "=== run_backup.sh MODE=$MODE TS=$TS RUN_DIR=$RUN_DIR ==="
mkdir -p "$RUN_DIR"

START_EPOCH=$(date +%s)
FAILED=0

run_component() {
    local name="$1"
    local script="$SCRIPT_DIR/component_${name}.sh"
    if [[ ! -x "$script" ]]; then
        log_warn "component_${name}.sh not present yet — skipping"
        return 0
    fi
    log_info "→ component: $name"
    if ! "$script" "$RUN_DIR"; then
        log_error "Component FAILED: $name"
        FAILED=1
    fi
}

case "$MODE" in
    daily)
        run_component db
        run_component code
        run_component gitbundle
        run_component config
        run_component volumes
        ;;
    weekly)
        run_component db
        run_component code
        run_component gitbundle
        run_component config
        run_component volumes
        run_component convlogs
        run_component kb_export
        run_component vps_pull
        ;;
    monthly)
        run_component db
        run_component code
        run_component gitbundle
        run_component config
        run_component volumes
        run_component convlogs
        run_component kb_export
        run_component vps_pull
        run_component monthly_full
        ;;
    db|code|gitbundle|config|volumes|convlogs|kb_export|vps_pull|monthly_full)
        run_component "$MODE"
        ;;
    *)
        log_error "Unknown MODE: $MODE"
        exit 1
        ;;
esac

if (( FAILED == 0 )); then
    log_info "All components OK — starting tier sync"
    "$SCRIPT_DIR/tier_sync_usb.py"    "$RUN_DIR"        || log_warn "USB tier sync had errors"
    "$SCRIPT_DIR/tier_sync_gdrive.py" "$RUN_DIR" "$MODE" || log_warn "GDrive tier sync had errors"
    "$SCRIPT_DIR/tier_sync_vps.sh"    "$RUN_DIR"        || log_warn "VPS tier sync had errors"
    "$SCRIPT_DIR/retention_prune.py"                    || log_warn "Retention prune had errors"
else
    log_error "Component failures — skipping tier sync + retention"
    notify_telegram error "Primary backup failed: mode=$MODE ts=$TS run=$RUN_DIR"
fi

DUR_MS=$(( ( $(date +%s) - START_EPOCH ) * 1000 ))
SIZE=$(dir_size_bytes "$RUN_DIR")
log_to_db "run_backup" "primary" \
    "$([[ $FAILED -eq 0 ]] && echo success || echo failed)" \
    "$RUN_DIR" "$SIZE" "$DUR_MS"

log_info "=== run_backup.sh DONE mode=$MODE failed=$FAILED size=$SIZE dur_ms=$DUR_MS ==="
exit "$FAILED"
