#!/usr/bin/env bash
# scripts/backup/component_convlogs.sh <run_dir>
# Weekly archive of conversation_logs/ (Claude transcripts).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/convlogs"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/convlogs_$(backup_ts).tar.gz"

if [[ ! -d "$ARCHIE_REPO/conversation_logs" ]]; then
    log_warn "no conversation_logs dir — skipping"
    log_to_db "convlogs" "primary" "skipped" "" "0" "0" "no conversation_logs dir"
    exit 0
fi

tar -czf "$OUT_FILE" -C "$ARCHIE_REPO" conversation_logs 2>>"$BACKUP_LOG_FILE"
SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "convlogs OK — $SIZE bytes in ${DUR}ms"
log_to_db "convlogs" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
