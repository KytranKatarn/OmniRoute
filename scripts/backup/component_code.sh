#!/usr/bin/env bash
# scripts/backup/component_code.sh <run_dir>
# tar -czf of platform code (excludes .git, caches). .git itself is covered by component_gitbundle.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/code"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/archie_code_$(backup_ts).tar.gz"

tar -czf "$OUT_FILE" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    -C "$ARCHIE_REPO" \
    platform_v2 ai_bridge scripts database/migrations 2>>"$BACKUP_LOG_FILE"

SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))

if tar -tzf "$OUT_FILE" >/dev/null 2>&1; then
    log_info "code tar OK — $SIZE bytes in ${DUR}ms"
    log_to_db "code" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
else
    log_error "code tar failed integrity check"
    log_to_db "code" "primary" "failed" "$OUT_FILE" "$SIZE" "$DUR" "tar -tzf failed"
    exit 1
fi
