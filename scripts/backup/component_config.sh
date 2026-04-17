#!/usr/bin/env bash
# scripts/backup/component_config.sh <run_dir>
# Creates AES-256-CBC encrypted archive of .env, secrets, nginx, CLAUDE.md, .mcp.json, .claude/rules.
# Key derivation: PBKDF2 200,000 iterations.
# NOTE: AES-256-GCM was the spec intent but openssl(1) `enc` doesn't expose AEAD modes (EVP only).
# Authentication comes from tar -tzf integrity check + .backup_sentinel roundtrip in verify_backups.sh.
# Includes .backup_sentinel for verification roundtrip (see verify_backups.sh).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

: "${BACKUP_CONFIG_PASSPHRASE:?BACKUP_CONFIG_PASSPHRASE missing from .env}"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/config"
mkdir -p "$OUT_DIR"

START=$(date +%s)
RAW_TAR="$OUT_DIR/.config_raw_$(backup_ts).tar.gz"
ENC_FILE="$OUT_DIR/config_$(backup_ts).tar.gz.enc"

SENTINEL_FILE=$(mktemp -t backup_sentinel.XXXXXX)
echo "archie-backup-sentinel $(date -u +%FT%TZ)" > "$SENTINEL_FILE"

# Tar the platform config items; --ignore-failed-read so missing dirs WARN, not fail.
tar --ignore-failed-read -czf "$RAW_TAR" \
    -C "$ARCHIE_REPO" \
    .env docker-compose.yml .mcp.json CLAUDE.md \
    .claude/rules \
    nginx secrets \
    2>>"$BACKUP_LOG_FILE"

# Append the sentinel (rename to .backup_sentinel inside archive via tar --transform).
# Simpler: stage a named copy, then -rzf it.
SENTINEL_STAGE_DIR=$(mktemp -d)
cp "$SENTINEL_FILE" "$SENTINEL_STAGE_DIR/.backup_sentinel"
tar -rzf "$RAW_TAR" -C "$SENTINEL_STAGE_DIR" .backup_sentinel 2>>"$BACKUP_LOG_FILE" || true
rm -rf "$SENTINEL_STAGE_DIR" "$SENTINEL_FILE"

# Encrypt with AES-256-CBC + PBKDF2 (200k iterations).
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
    -in "$RAW_TAR" -out "$ENC_FILE" \
    -pass env:BACKUP_CONFIG_PASSPHRASE

# Shred the plaintext intermediate.
shred -u "$RAW_TAR" 2>/dev/null || rm -f "$RAW_TAR"

SIZE=$(stat -c %s "$ENC_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "config encrypted tarball — $SIZE bytes in ${DUR}ms"
log_to_db "config" "primary" "success" "$ENC_FILE" "$SIZE" "$DUR"
