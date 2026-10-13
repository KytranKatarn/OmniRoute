#!/usr/bin/env bash
# scripts/backup/component_vps_pull.sh <run_dir>
# Weekly dump + pull of the watch-product / WTF databases from Citadel over mesh.
#
# PRE-REQ: key-based ssh from the hub to root@Citadel over the mesh (100.64.0.10). If unreachable the step logs "skipped" and exits 0
# (task #7183: it now FAILS, not skips, when a mapped database cannot be dumped or the pull does not verify).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/vps_pull"
mkdir -p "$OUT_DIR"

# Citadel / boston-2 (mesh 100.64.0.10, root@) hosts the watch products and What The Fact. This step dumps their databases there and
# pulls the dumps to the HUB, which then covers them with the normal retention / USB / Drive tiers. (An older version of this header
# called the step redundant because "Citadel is already backed up by the DR flow": it was not. DR replicates the hub's `archie` DB, and
# this step's old `${db}_db` / `-U postgres` assumptions matched no Citadel container, so these databases had NO dump for four months
# (task #7183); every failure also left a 0-byte /tmp/<name>.dump on Citadel because the redirect creates the file before the command runs.)
VPS_HOST="${BACKUP_VPS_HOST:-100.64.0.10}"
VPS_USER="${BACKUP_VPS_USER:-root}"
# (The snapshot is streamed out with `docker exec cat`, NOT `docker cp`: /tmp in these containers is a tmpfs and docker cp cannot read tmpfs.)
# Staging dir on Citadel's disk (not /tmp). A dump is written as *.partial and only renamed once it validated.
REMOTE_DIR="${BACKUP_VPS_REMOTE_DIR:-/opt/archie-products/_backups/vps_pull}"

START=$(date +%s)

# Fast-fail if mesh is unreachable — avoid 10-min rsync timeout.
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${VPS_USER}@${VPS_HOST}" 'echo ok' >/dev/null 2>&1; then
    log_warn "VPS ${VPS_HOST} not reachable — skipping vps_pull"
    log_to_db "vps_pull" "primary" "skipped" "" "0" "0" "mesh/ssh unreachable"
    exit 0
fi

# One line per source: kind|label|container|role-or-path|database. The container names are Citadel's REAL ones; an entry whose
# container is gone is a FAILURE (not a quiet skip), so a product that moves again cannot go unbacked for months.
#   pg     : pg_dump -Fc inside the container, validated with pg_restore -l
#   sqlite : online-consistent copy through python's sqlite3 backup API, validated with PRAGMA integrity_check
SOURCES=(
    "pg|wtf|what-the-fact-wtf-postgres-1|wtfuser|wtf"
    "pg|gov_watch|gov_watch_db|gov_watch|gov_watch"
    "sqlite|civic_watch|kytran_watch_api|/app/data/watch.db|"
    "sqlite|legal_watch|kytran_legal_api|/app/data/legal.db|"
    "sqlite|market_watch|kytran_market_api|/app/data/market.db|"
)

FAILED=0
DAY=$(date +%Y%m%d)
ssh "${VPS_USER}@${VPS_HOST}" "mkdir -p '${REMOTE_DIR}'" 2>>"$BACKUP_LOG_FILE" || { log_error "cannot create ${REMOTE_DIR} on ${VPS_HOST}"; FAILED=1; }

dump_remote() { # kind label container arg1 arg2 -> prints the remote file name on success
    local kind="$1" label="$2" ctr="$3" a1="$4" a2="$5"
    local base="${label}_${DAY}" part
    if [[ "$kind" == "pg" ]]; then
        part="${REMOTE_DIR}/${base}.dump"
        ssh "${VPS_USER}@${VPS_HOST}" "set -e; docker exec '${ctr}' pg_dump -U '${a1}' -d '${a2}' -Fc -Z 6 > '${part}.partial'; \
            test \"\$(docker exec -i '${ctr}' pg_restore -l < '${part}.partial' | grep -c .)\" -gt 10; mv -f '${part}.partial' '${part}'" \
            2>>"$BACKUP_LOG_FILE" || { ssh "${VPS_USER}@${VPS_HOST}" "rm -f '${part}.partial'" 2>/dev/null; return 1; }
    else
        part="${REMOTE_DIR}/${base}.db"
        ssh "${VPS_USER}@${VPS_HOST}" "set -e; docker exec '${ctr}' python3 -c \"import sqlite3,sys; s=sqlite3.connect('file:${a1}?mode=ro',uri=True); d=sqlite3.connect('/tmp/_vps_pull_snap.db'); s.backup(d); r=d.execute('pragma integrity_check').fetchone()[0]; d.close(); sys.exit(0 if r=='ok' else 3)\"; \
            docker exec '${ctr}' cat /tmp/_vps_pull_snap.db > '${part}.partial'; docker exec '${ctr}' rm -f /tmp/_vps_pull_snap.db; mv -f '${part}.partial' '${part}'" \
            2>>"$BACKUP_LOG_FILE" || { ssh "${VPS_USER}@${VPS_HOST}" "rm -f '${part}.partial'; docker exec '${ctr}' rm -f /tmp/_vps_pull_snap.db" 2>/dev/null; return 1; }
    fi
    echo "$part"
}

for entry in "${SOURCES[@]}"; do
    IFS='|' read -r kind label ctr a1 a2 <<<"$entry"
    if ! remote_file="$(dump_remote "$kind" "$label" "$ctr" "$a1" "$a2")"; then
        log_error "VPS dump FAILED for $label (container=$ctr) — see $BACKUP_LOG_FILE"
        FAILED=1
        continue
    fi
    # Pull, then compare checksums before the Citadel copy is removed.
    if rsync -a "${VPS_USER}@${VPS_HOST}:${remote_file}" "$OUT_DIR/" 2>>"$BACKUP_LOG_FILE"; then
        local_file="$OUT_DIR/$(basename "$remote_file")"
        want="$(ssh "${VPS_USER}@${VPS_HOST}" "sha256sum '${remote_file}'" 2>>"$BACKUP_LOG_FILE" | cut -d' ' -f1)"
        have="$(sha256sum "$local_file" | cut -d' ' -f1)"
        if [[ -n "$want" && "$want" == "$have" && -s "$local_file" ]]; then
            ssh "${VPS_USER}@${VPS_HOST}" "rm -f '${remote_file}'" 2>>"$BACKUP_LOG_FILE" || true
            log_info "VPS dump OK: $label ($(stat -c %s "$local_file") bytes)"
        else
            log_error "VPS dump $label: checksum mismatch after pull (remote=$want local=$have) — Citadel copy kept"
            rm -f "$local_file"; FAILED=1
        fi
    else
        log_error "VPS dump $label: rsync pull failed — Citadel copy kept"
        FAILED=1
    fi
done

# Pull each product's persistence dir.
ssh "${VPS_USER}@${VPS_HOST}" 'ls -d /root/*/persistence 2>/dev/null || true' | while read -r rp; do
    [[ -z "$rp" ]] && continue
    name=$(echo "$rp" | awk -F/ '{print $(NF-1)}')
    rsync -az "${VPS_USER}@${VPS_HOST}:${rp}" "$OUT_DIR/${name}_persistence" 2>>"$BACKUP_LOG_FILE" || FAILED=1
done

SIZE=$(dir_size_bytes "$OUT_DIR")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_info "vps_pull $STATUS — $SIZE bytes in ${DUR}ms"
log_to_db "vps_pull" "primary" "$STATUS" "$OUT_DIR" "$SIZE" "$DUR"
exit "$FAILED"
