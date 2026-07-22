#!/usr/bin/env bash
# scripts/backup/lib_common.sh
# Shared helpers for all backup components. Sourced by every script;
# do NOT execute directly.
#
# Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md
# Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md

set -euo pipefail

# ---------- Paths ----------
BACKUP_ROOT="${BACKUP_ROOT:-/mnt/data2/backups}"   # Stays on /mnt/data2 until host perms on /mnt/data are fixed.
BACKUP_USB="${BACKUP_USB:-/mnt/external-backup}"
BACKUP_LOCK="${BACKUP_ROOT}/.backup_lock"
BACKUP_LOG_FILE="${BACKUP_LOG_FILE:-/var/log/archie_backup.log}"
ARCHIE_REPO="${ARCHIE_REPO:-/mnt/archie_brain}"

# Fall back to /tmp if /var/log isn't writable (user crontab scenario).
if ! [[ -w "$(dirname "$BACKUP_LOG_FILE")" ]]; then
    BACKUP_LOG_FILE=/tmp/archie_backup.log
fi

# ---------- Logging ----------
log() {
    local level="$1"; shift
    local msg="$*"
    local ts; ts=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
    echo "[$ts] [$level] [$(basename "${BASH_SOURCE[1]:-backup}")] $msg" | tee -a "$BACKUP_LOG_FILE" >&2
}
log_info()  { log INFO  "$@"; }
log_warn()  { log WARN  "$@"; }
log_error() { log ERROR "$@"; }

# ---------- Lock ----------
acquire_lock() {
    local name="$1" timeout_sec="${2:-7200}"   # 2h default
    if [[ -f "$BACKUP_LOCK" ]]; then
        local lock_age; lock_age=$(( $(date +%s) - $(stat -c %Y "$BACKUP_LOCK") ))
        if (( lock_age < timeout_sec )); then
            log_error "Backup lock held ($(cat "$BACKUP_LOCK")), age ${lock_age}s < ${timeout_sec}s — exiting"
            return 2
        fi
        log_warn "Stale lock (age ${lock_age}s) — reclaiming"
    fi
    echo "pid=$$ name=$name started=$(date -u +%FT%TZ)" > "$BACKUP_LOCK"
    trap 'release_lock' EXIT INT TERM
}
release_lock() {
    rm -f "$BACKUP_LOCK" 2>/dev/null || true
}

# ---------- DB ----------
psql_archie() {
    docker exec -i archie_database psql -U archie -d archie "$@"
}

# Insert row in backup_log using the canonical schema (component/tier/size_bytes).
# Falls back to legacy schema (backup_type/file_size_bytes) if the migration hasn't run.
log_to_db() {
    local component="$1" tier="$2" status="$3" path="$4" size="${5:-0}" duration_ms="${6:-0}" err="${7:-}"
    local esc_err; esc_err=$(printf '%s' "$err" | sed "s/'/''/g")
    # Stamp the CURRENT platform build (#5087) so automated/component rows show "Build #N"
    # instead of "Build #-" in the Backups list. Read-only: the button/programmatic path OWNS
    # the counter via set_build_number(); a nightly must record the build it ran under, never
    # bump it. Guard with [[ -r ]] + a direct read (NOT `cat file | tr`): under this script's
    # `set -euo pipefail`, a cat of a MISSING file fails the pipeline and would abort the run.
    # tr -dc keeps digits only, so an empty/garbled file yields '' -> SQL NULL.
    local build=""
    if [[ -r "${BACKUP_ROOT}/.current_build" ]]; then
        build=$(tr -dc '0-9' < "${BACKUP_ROOT}/.current_build")
    fi
    local build_sql="NULL"; [[ -n "$build" ]] && build_sql="$build"
    psql_archie <<SQL 2>>"$BACKUP_LOG_FILE" >/dev/null || log_warn "Failed to write backup_log row for $component/$tier"
DO \$\$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='backup_log' AND column_name='component') THEN
        INSERT INTO backup_log
            (component, tier, status, file_path, size_bytes, duration_ms, error_message, build_number, created_at)
        VALUES
            ('$component', '$tier', '$status', '$path', $size, $duration_ms,
             NULLIF('$esc_err', ''), $build_sql, NOW());
    ELSE
        INSERT INTO backup_log
            (backup_type, file_path, file_size_bytes, status, error_message, completed_at, created_at)
        VALUES
            ('$component', '$path', $size, '$status',
             NULLIF('$esc_err', ''), NOW(), NOW());
    END IF;
END \$\$;
SQL
}

# ---------- Telegram ----------
notify_telegram() {
    local severity="$1"; shift
    local msg="$*"
    docker exec archie_platform python3 -c "
from services.telegram_service import send_archie_alert
send_archie_alert('$severity', '''$msg''', source_agent='backup_system')
" 2>&1 | tail -1 >> "$BACKUP_LOG_FILE" || log_warn "Telegram notify failed (continuing)"
}

# ---------- Passphrase loader ----------
load_backup_env() {
    if [[ ! -f "${ARCHIE_REPO}/.env" ]]; then
        log_error ".env not found at ${ARCHIE_REPO}/.env"
        return 1
    fi
    # Parse KEY=VALUE literally instead of `source`-ing the file. Several .env
    # values are unquoted secrets containing shell metacharacters (^ $ ( ) etc.)
    # which break `source` with "command not found" / exit 127 — that silently
    # failed the config component (and skipped tier-sync + retention) every
    # night (#4045). Splitting on the first '=' and exporting verbatim is
    # metacharacter-proof and needs no `set +u`/positional-var hacks.
    local line key val
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue          # comment
        [[ "$line" != *=* ]] && continue                     # not a KEY=VALUE
        key="${line%%=*}"
        key="${key#"${key%%[![:space:]]*}"}"                 # ltrim
        key="${key%"${key##*[![:space:]]}"}"                 # rtrim
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue # valid env name
        val="${line#*=}"                                     # everything after first '='
        # strip one layer of surrounding matching quotes, if present
        if [[ "$val" == \"*\" && ${#val} -ge 2 ]]; then val="${val:1:${#val}-2}"
        elif [[ "$val" == \'*\' && ${#val} -ge 2 ]]; then val="${val:1:${#val}-2}"; fi
        export "$key=$val"
    done < "${ARCHIE_REPO}/.env"
}

# ---------- Utilities ----------
backup_ts() { date -u +'%Y%m%d_%H%M%S'; }

dir_size_bytes() {
    du -sb "$1" 2>/dev/null | awk '{print $1}' || echo 0
}
