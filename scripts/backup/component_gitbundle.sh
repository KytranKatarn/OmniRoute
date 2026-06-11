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
CRITICAL_FAILED=0   # only the platform repo (archie_brain) failing blocks the run
SOFT_FAILED=0       # a standalone repo failing must NOT skip tier-sync+retention (#4045)
OK_COUNT=0
START=$(date +%s)

# archie_brain is the critical platform repo; a single standalone repo failing
# degrades to a warning so one bad clone can't fail the whole component and skip
# tier-sync + retention (the #4045 nightly cascade).
fail_repo() {
    local repo="$1" reason="$2"
    if [[ "$repo" == "archie_brain" ]]; then
        log_error "bundle $repo: $reason"; CRITICAL_FAILED=1
    else
        log_warn "bundle $repo: $reason (non-critical — continuing)"; SOFT_FAILED=$(( SOFT_FAILED + 1 ))
    fi
}

for entry in "${REPOS[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    if [[ ! -d "$path/.git" ]]; then
        log_warn "skip $name — $path is not a git repo"
        continue
    fi
    OUT_FILE="$OUT_DIR/${name}_${BUNDLE_KIND}_$(backup_ts).bundle"
    if git -C "$path" bundle create "$OUT_FILE" "${RANGE_ARGS[@]}" 2>>"$BACKUP_LOG_FILE"; then
        # Verify against the bundle's OWN repo (-C "$path"). Without it, git
        # verifies against the CWD repo (archie_brain), so any incremental
        # bundle whose prerequisite commit lives only in the source repo always
        # "fails verify" — the #4045 root cause (creed/business-suite/archie-code).
        if git -C "$path" bundle verify "$OUT_FILE" >/dev/null 2>&1; then
            sz=$(stat -c %s "$OUT_FILE")
            TOTAL_SIZE=$(( TOTAL_SIZE + sz ))
            OK_COUNT=$(( OK_COUNT + 1 ))
            log_info "bundle $name $BUNDLE_KIND OK — $sz bytes"
        else
            fail_repo "$name" "failed verify"
        fi
    else
        fail_repo "$name" "git bundle create failed"
    fi
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
# Fail (rc=1 -> run_backup skips retention) only if the platform repo failed or
# nothing bundled. A partial (some standalone repos failed) exits 0 so the
# nightly tier-sync + retention still run.
if [[ $CRITICAL_FAILED -ne 0 || $OK_COUNT -eq 0 ]]; then
    STATUS=failed; RC=1
elif [[ $SOFT_FAILED -ne 0 ]]; then
    STATUS=partial; RC=0
else
    STATUS=success; RC=0
fi
log_to_db "gitbundle" "primary" "$STATUS" "$OUT_DIR" "$TOTAL_SIZE" "$DUR"
exit "$RC"
