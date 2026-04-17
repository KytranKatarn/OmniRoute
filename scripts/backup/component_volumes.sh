#!/usr/bin/env bash
# scripts/backup/component_volumes.sh <run_dir>
# Captures stateful service data dirs. Missing volumes skipped with WARN.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/volumes"
mkdir -p "$OUT_DIR"

START=$(date +%s)

# Name:Path pairs. Order matters only for logging clarity.
VOLUMES=(
    "n8n:/mnt/archie_brain/persistence/n8n"
    "kbs:/mnt/archie_brain/kytran-business-suite/data"
    "creed:/mnt/archie_brain/kytran-creed/data"
    "stalwart:/mnt/archie_brain/persistence/stalwart"
)

TOTAL=0
FAILED=0
for entry in "${VOLUMES[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    if [[ ! -d "$path" ]]; then
        log_warn "skip volume $name — $path not present"
        continue
    fi
    OUT_FILE="$OUT_DIR/volume_${name}_$(backup_ts).tar.gz"
    # Exclude subdirs owned by other UIDs we can't read (e.g. kytran-creed/data/postgres owned by uid 70).
    # Those need their own pg_dumpall-based components (TODO: component_creed_db.sh, component_kbs_db.sh).
    if tar --ignore-failed-read \
           --exclude='*/postgres' \
           --exclude='*/postgres-data' \
           -czf "$OUT_FILE" -C "$(dirname "$path")" "$(basename "$path")" 2>>"$BACKUP_LOG_FILE"; then
        sz=$(stat -c %s "$OUT_FILE")
        TOTAL=$(( TOTAL + sz ))
        log_info "volume $name OK — $sz bytes (postgres subdirs excluded — see TODO)"
    else
        log_error "volume $name tar failed"
        FAILED=1
    fi
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "volumes" "primary" "$STATUS" "$OUT_DIR" "$TOTAL" "$DUR"
exit "$FAILED"
