#!/usr/bin/env bash
# scripts/backup/component_kb_export.sh <run_dir>
# Weekly data-only export of knowledge_base table (separate from full DB dump).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/kb_export"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/kb_$(backup_ts).dump"

docker exec archie_database pg_dump -U archie -d archie \
    --data-only -t knowledge_base -Fc -Z 6 > "$OUT_FILE"

SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "kb_export OK — $SIZE bytes in ${DUR}ms"
log_to_db "kb_export" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
