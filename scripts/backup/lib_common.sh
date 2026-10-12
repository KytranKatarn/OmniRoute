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

# gitbundle_repos: one "<name>:<path>" line per repo that gets a git bundle. This is the SINGLE definition: component_gitbundle.sh
# creates bundles from it and verify_backups.sh maps a bundle back to its source repo through it, so the two cannot drift.
# The platform repo is always the root; every other subdir with a .git is auto-discovered (task #2077), name normalised
# (kytran-business-suite -> kytran_business_suite). GITBUNDLE_ROOT exists for tests; production leaves it at /mnt/archie_brain.
gitbundle_repos() {
    local root="${GITBUNDLE_ROOT:-/mnt/archie_brain}" sub base
    echo "archie_brain:${root}"
    for sub in "${root}"/*/; do
        [[ -d "${sub}.git" ]] || continue
        base="$(basename "${sub%/}")"
        [[ "$base" == ".git" ]] && continue
        echo "${base//-/_}:${sub%/}"
    done
}

# _bundle_key <name>: canonical form so every producer's spelling of a repo meets (kytran-business-suite, kytran_business_suite, business-suite).
_bundle_key() { local k="${1,,}"; k="${k#kytran[-_]}"; echo "${k//-/_}"; }

# verify_gitbundle <bundle>: verify an INCREMENTAL/FULL bundle inside its OWN source repo. `git bundle verify` needs the repository
# the bundle was cut from: run with no repo (cron's cwd is /home/kytran) it ALWAYS fails ("need a repository to verify a bundle"),
# and run in the wrong repo it fails on missing prerequisite commits. The weekly verify therefore failed every Sunday while the
# bundles themselves were fine (task #7182). `git bundle verify` alone is also too weak (it never reads the pack), so the pack is
# validated too. Returns 0 verified, 1 verification failed, 2 name not <repo>_<kind>_<ts>.bundle,
# 3 no source repo found (cannot be verified: not the same thing as corrupt).
verify_gitbundle() {
    local bundle="$1" file name entry repo=""
    file="$(basename "$bundle")"
    # TWO producers write bundles with DIFFERENT names: component_gitbundle.sh -> <repo>_<incremental|full>_<ts>.bundle, and the nightly
    # backup_triage.sh -> <name>_<ts>.bundle with "kytran-" stripped (business-suite, server-manager, creed, archie_brain). The nightly
    # one is what the cron actually produces, so it must parse too (a first version only knew the former and skipped every real bundle).
    if [[ "$file" =~ ^(.+)_(incremental|full)_[0-9]{8}_[0-9]{6}\.bundle$ ]] || [[ "$file" =~ ^(.+)_[0-9]{8}_[0-9]{6}\.bundle$ ]]; then
        name="${BASH_REMATCH[1]}"
    else
        return 2
    fi
    local want have
    want="$(_bundle_key "$name")"
    while IFS= read -r entry; do
        have="$(_bundle_key "${entry%%:*}")"
        [[ "$have" == "$want" ]] && repo="${entry#*:}"
    done < <(gitbundle_repos)
    [[ -n "$repo" && -d "$repo/.git" ]] || return 3
    # 1. header + prerequisites (cheap). Any failure is normalised to 1: git exits 128 on a fatal, which is not our contract.
    git -C "$repo" bundle verify "$bundle" >/dev/null 2>&1 || return 1
    # 2. `bundle verify` does NOT read the pack: a truncated or bit-flipped bundle still passes it. Unbundle into a THROWAWAY object
    #    directory (the live repo is only an alternate, to resolve an incremental bundle's thin-pack bases): index-pack then checks
    #    every object. Nothing is written to the repo, and refs are not touched by `unbundle`.
    local tmp rc=1 objdir
    objdir="$(git -C "$repo" rev-parse --absolute-git-dir 2>/dev/null)/objects"
    # Scratch lives on the BACKUP disk, not /tmp: the pack is as large as the bundle (150 MB+ and growing) and /tmp is a small tmpfs, where
    # a first version ran out of space and reported a perfectly good bundle as corrupt.
    tmp="$(mktemp -d "${BACKUP_ROOT:-${TMPDIR:-/tmp}}/.verify_pack.XXXXXX")" || return 1
    mkdir -p "$tmp/pack"
    GIT_OBJECT_DIRECTORY="$tmp" GIT_ALTERNATE_OBJECT_DIRECTORIES="$objdir" \
        git -C "$repo" bundle unbundle "$bundle" >/dev/null 2>&1 && rc=0
    rm -rf "$tmp"
    return "$rc"
}

dir_size_bytes() {
    du -sb "$1" 2>/dev/null | awk '{print $1}' || echo 0
}
