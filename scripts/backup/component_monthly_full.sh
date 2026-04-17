#!/usr/bin/env bash
# scripts/backup/component_monthly_full.sh <run_dir>
# Tars every sibling component dir under the monthly run's parent.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/monthly_full"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/monthly_full_$(backup_ts).tar.gz"

# Tar every component dir sibling except ourselves.
SIBLINGS=()
while IFS= read -r d; do
    [[ "$d" == "monthly_full" ]] && continue
    SIBLINGS+=("$d")
done < <(ls "$RUN_DIR")

if (( ${#SIBLINGS[@]} == 0 )); then
    log_warn "no sibling components to tar — skipping monthly_full"
    log_to_db "monthly_full" "primary" "skipped" "" "0" "0" "no siblings"
    exit 0
fi

tar -czf "$OUT_FILE" -C "$RUN_DIR" "${SIBLINGS[@]}" 2>>"$BACKUP_LOG_FILE"

SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "monthly_full OK — $SIZE bytes in ${DUR}ms"
log_to_db "monthly_full" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
