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

# Lint/test caches are excluded for two reasons: they are worthless in a restore, and
# their contents are frequently written by tooling running as root with mode 0600
# (ruff writes /platform_v2/.ruff_cache/<ver>/<hash> as root:root -rw-------). The
# unprivileged backup user then cannot read them, tar exits non-zero, and — with
# `set -e` above — this script dies at the tar, BEFORE the integrity check below ever
# runs. That is #5052: the archive was complete and valid every single night, but the
# component was reported FAILED, which made run_backup.sh skip tier sync + retention.
# Same root cause as #2369, which fixed it in backup_triage.sh only; this per-component
# pipeline never got the same treatment.
#
# `|| tar_rc=$?` is load-bearing: without it `set -e` still kills the script on any tar
# warning (a file changing mid-read is exit 1 and is NOT a corrupt archive).
tar_rc=0
tar -czf "$OUT_FILE" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    --exclude='.ruff_cache' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.tox' \
    -C "$ARCHIE_REPO" \
    platform_v2 ai_bridge scripts database/migrations 2>>"$BACKUP_LOG_FILE" || tar_rc=$?

SIZE=$(stat -c %s "$OUT_FILE" 2>/dev/null || echo 0)
DUR=$(( ( $(date +%s) - START ) * 1000 ))

# Judge the ARTIFACT, not tar's exit code (#2369). gzip -t proves the stream is intact;
# tar -tzf proves the member index is readable. A non-zero tar_rc with a valid archive is
# a WARNING worth surfacing, never a reason to condemn the run and skip tier sync.
if gzip -t "$OUT_FILE" 2>/dev/null && tar -tzf "$OUT_FILE" >/dev/null 2>&1; then
    if (( tar_rc != 0 )); then
        log_warn "code tar exited $tar_rc but the archive verifies — treating as success (see $BACKUP_LOG_FILE for skipped files)"
        log_info "code tar OK (rc=$tar_rc, verified) — $SIZE bytes in ${DUR}ms"
        log_to_db "code" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR" "tar rc=$tar_rc; artifact verified"
    else
        log_info "code tar OK — $SIZE bytes in ${DUR}ms"
        log_to_db "code" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
    fi
else
    log_error "code tar failed integrity check (tar rc=$tar_rc)"
    log_to_db "code" "primary" "failed" "$OUT_FILE" "$SIZE" "$DUR" "artifact failed gzip -t / tar -tzf (tar rc=$tar_rc)"
    exit 1
fi
