#!/usr/bin/env bash
# scripts/backup/component_db.sh <run_dir>
# pg_dump -Fc (custom format, compressed). Output: <run_dir>/database/archie_<ts>.dump
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/database"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/archie_$(backup_ts).dump"

if docker exec archie_database pg_dump -U archie -d archie -Fc -Z 6 > "$OUT_FILE"; then
    SIZE=$(stat -c %s "$OUT_FILE")
    DUR=$(( ( $(date +%s) - START ) * 1000 ))
    log_info "DB dump OK — $SIZE bytes in ${DUR}ms"
    log_to_db "db" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
else
    DUR=$(( ( $(date +%s) - START ) * 1000 ))
    log_error "pg_dump failed"
    log_to_db "db" "primary" "failed" "$OUT_FILE" "0" "$DUR" "pg_dump nonzero exit"
    exit 1
fi
