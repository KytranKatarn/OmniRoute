#!/usr/bin/env bash
# scripts/backup/component_gitbundle.sh <run_dir>
# Full --all bundle on 1st of month; --since=1.month.ago otherwise.
# Bundles archie_brain and all standalone repos that have .git present.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/gitbundles"
mkdir -p "$OUT_DIR"

DOM=$(date +%d)
if [[ "$DOM" == "01" ]]; then
    RANGE_ARGS=( --all )
    BUNDLE_KIND="full"
else
    RANGE_ARGS=( --all --since=1.month.ago )
    BUNDLE_KIND="incremental"
fi

# Repos to bundle. The main platform repo is always /mnt/archie_brain; every
# other local subdir is auto-discovered by the presence of a .git dir. This
# stops us from missing newly-cloned standalones (archie-code was missed in
# the original hardcoded list — task #2077).
REPOS=( "archie_brain:/mnt/archie_brain" )
for sub in /mnt/archie_brain/*/; do
    [[ -d "${sub}.git" ]] || continue
    base="$(basename "${sub%/}")"
    [[ "$base" == ".git" ]] && continue
    # Normalize name: kytran-business-suite -> kytran_business_suite
    name="${base//-/_}"
    REPOS+=( "${name}:${sub%/}" )
done

TOTAL_SIZE=0
FAILED=0
START=$(date +%s)

for entry in "${REPOS[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    if [[ ! -d "$path/.git" ]]; then
        log_warn "skip $name — $path is not a git repo"
        continue
    fi
    OUT_FILE="$OUT_DIR/${name}_${BUNDLE_KIND}_$(backup_ts).bundle"
    if git -C "$path" bundle create "$OUT_FILE" "${RANGE_ARGS[@]}" 2>>"$BACKUP_LOG_FILE"; then
        if git bundle verify "$OUT_FILE" >/dev/null 2>&1; then
            sz=$(stat -c %s "$OUT_FILE")
            TOTAL_SIZE=$(( TOTAL_SIZE + sz ))
            log_info "bundle $name $BUNDLE_KIND OK — $sz bytes"
        else
            log_error "bundle $name failed verify"
            FAILED=1
        fi
    else
        log_error "git bundle create failed for $name"
        FAILED=1
    fi
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "gitbundle" "primary" "$STATUS" "$OUT_DIR" "$TOTAL_SIZE" "$DUR"
exit "$FAILED"
