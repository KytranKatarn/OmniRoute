#!/usr/bin/env bash
# scripts/backup/decrypt_restore.sh <encrypted_file> <passphrase_env_var>
#
# Example:
#   set -o allexport; source /mnt/archie_brain/.env; set +o allexport
#   ./decrypt_restore.sh /mnt/data2/backups/.../config_20260420_xxx.tar.gz.enc BACKUP_CONFIG_PASSPHRASE
#
# Decrypts <encrypted_file> (produced by component_config.sh or either
# encrypted tier-sync) to <encrypted_file without .enc> in the same directory.
#
# Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 18

set -euo pipefail

FILE="${1:?encrypted file required}"
VAR="${2:?passphrase env var name required}"

if [[ -z "${!VAR:-}" ]]; then
    echo "Env var \$$VAR is empty." >&2
    echo "Load from .env first:" >&2
    echo "  set -o allexport; source /mnt/archie_brain/.env; set +o allexport" >&2
    exit 1
fi

if [[ ! -f "$FILE" ]]; then
    echo "File not found: $FILE" >&2
    exit 1
fi

OUT="${FILE%.enc}"
if [[ -e "$OUT" ]]; then
    echo "Refusing to overwrite existing file: $OUT" >&2
    exit 1
fi

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
    -in "$FILE" -out "$OUT" -pass "env:$VAR"
echo "Decrypted → $OUT"
