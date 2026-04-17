#!/usr/bin/env bash
# scripts/backup/verify_backups.sh
# Weekly integrity verification of the newest backup per component.
# Writes verification_status='verified' on success, 'failed' otherwise.
# Telegram alert on any failure.
#
# Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md §9
# Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 18

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

RESULT=0

latest_file_under() (
    # Subshell with pipefail OFF: `head -1` closing the pipe SIGPIPEs `sort`,
    # which pipefail would treat as an error and kill the whole verify run.
    set +o pipefail
    find "$1" -type f -name "$2" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-
)

mark_verified() {
    local path="$1"
    psql_archie -c "UPDATE backup_log SET verification_status='verified' WHERE file_path='$path';" >/dev/null 2>&1 || true
}

mark_failed() {
    local path="$1" reason="$2"
    local esc; esc=$(printf '%s' "$reason" | sed "s/'/''/g")
    psql_archie -c "UPDATE backup_log SET verification_status='failed', notes=COALESCE(notes,'')||'; verify: $esc' WHERE file_path='$path';" >/dev/null 2>&1 || true
}

# -------- 1. DB dump (pg_restore --list) --------
DB_FILE=$(latest_file_under "$BACKUP_ROOT" "*.dump")
if [[ -n "$DB_FILE" ]]; then
    if docker exec -i archie_database pg_restore --list < "$DB_FILE" >/dev/null 2>&1; then
        log_info "verify OK: db ($DB_FILE)"
        mark_verified "$DB_FILE"
    else
        log_error "verify FAIL: db ($DB_FILE)"
        mark_failed "$DB_FILE" "pg_restore --list failed"
        RESULT=1
        notify_telegram error "Backup verify failed: DB dump ($DB_FILE)"
    fi
else
    log_warn "verify: no DB dump found under $BACKUP_ROOT"
fi

# -------- 2. Code tar (tar -tzf) --------
CODE_FILE=$(latest_file_under "$BACKUP_ROOT" "archie_code_*.tar.gz")
if [[ -n "$CODE_FILE" ]]; then
    if tar -tzf "$CODE_FILE" >/dev/null 2>&1; then
        log_info "verify OK: code ($CODE_FILE)"
        mark_verified "$CODE_FILE"
    else
        log_error "verify FAIL: code ($CODE_FILE)"
        mark_failed "$CODE_FILE" "tar -tzf failed"
        RESULT=1
    fi
else
    log_warn "verify: no code tar found"
fi

# -------- 3. Git bundles (git bundle verify) --------
# mapfile + process-substitution is more reliable than while-read + <<< under set -euo pipefail.
mapfile -t BUNDLE_ARR < <(set +o pipefail; find "$BACKUP_ROOT" -type f -name "*_*.bundle" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -4 | cut -d' ' -f2-)
if (( ${#BUNDLE_ARR[@]} > 0 )); then
    for bundle in "${BUNDLE_ARR[@]}"; do
        [[ -z "$bundle" ]] && continue
        if git bundle verify "$bundle" >/dev/null 2>&1; then
            log_info "verify OK: gitbundle ($(basename "$bundle"))"
            mark_verified "$bundle"
        else
            log_error "verify FAIL: gitbundle ($bundle)"
            mark_failed "$bundle" "git bundle verify failed"
            RESULT=1
        fi
    done
else
    log_warn "verify: no git bundles found"
fi

# -------- 4. Config encryption roundtrip --------
CFG=$(latest_file_under "$BACKUP_ROOT" "config_*.tar.gz.enc")
if [[ -n "$CFG" && -n "${BACKUP_CONFIG_PASSPHRASE:-}" ]]; then
    TMP=$(mktemp -d)
    if openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
         -in "$CFG" -out "$TMP/c.tar.gz" -pass env:BACKUP_CONFIG_PASSPHRASE 2>/dev/null \
       && tar -xzf "$TMP/c.tar.gz" -C "$TMP" .backup_sentinel 2>/dev/null \
       && head -1 "$TMP/.backup_sentinel" 2>/dev/null | grep -q "archie-backup-sentinel"; then
        log_info "verify OK: config encryption roundtrip"
        mark_verified "$CFG"
    else
        log_error "verify FAIL: config encryption roundtrip"
        mark_failed "$CFG" "decrypt or sentinel check failed"
        RESULT=1
        notify_telegram error "Backup verify failed: config encryption roundtrip"
    fi
    rm -rf "$TMP"
elif [[ -z "$CFG" ]]; then
    log_warn "verify: no encrypted config found"
elif [[ -z "${BACKUP_CONFIG_PASSPHRASE:-}" ]]; then
    log_warn "verify: BACKUP_CONFIG_PASSPHRASE not loaded — skipping config roundtrip"
fi

# -------- Summary row --------
if (( RESULT == 0 )); then
    log_to_db "verify" "primary" "success" "$BACKUP_ROOT" "0" "0" ""
else
    log_to_db "verify" "primary" "failed" "$BACKUP_ROOT" "0" "0" "one or more artifacts failed verification"
fi

exit "$RESULT"
