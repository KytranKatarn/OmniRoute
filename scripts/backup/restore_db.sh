#!/usr/bin/env bash
# scripts/backup/restore_db.sh — the real DB recovery tool for Phase 1-6 (-Fc) backups.
# Task #4049. Pairs with dr_drill.sh (verify-only drill) and component_db.sh (the -Fc dumper).
#
# SAFE BY DEFAULT: with no --force, a dump is verified by restoring it into a THROWAWAY
# pgvector container (mounted read-only, auto-removed) — production is never touched. This is
# the same proven path dr_drill.sh uses (0.0000% delta on archie/knowledge_base).
#
# PROD RESTORE is destructive and requires BOTH --force AND DR_CONFIRM=RESTORE-NOW. It
# terminates live backends, DROPs and recreates the target DB, then pg_restores into it. For the
# `archie` DB this restores the platform's OWN database — stop archie_platform first.
#
# Usage:
#   restore_db.sh <backup_dir> [--db archie|wtf|creed|all] [--into-scratch|--force] [--keep-scratch]
#
# Examples:
#   restore_db.sh /mnt/data2/backups/20260611_145520_Daily_Triage --db archie        # safe verify
#   restore_db.sh /mnt/data2/backups/20260611_145520_Daily_Triage --db all           # verify all
#   DR_CONFIRM=RESTORE-NOW restore_db.sh /mnt/data2/backups/<dir> --db archie --force # PROD restore
#
# Runbook: KB #272184.
set -euo pipefail

SCRATCH_IMAGE="pgvector/pgvector:pg16"

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

log()  { echo "[restore_db] $*"; }
die()  { echo "[restore_db] ERROR: $*" >&2; exit 1; }

# ---- parse args ----------------------------------------------------------------------------
BACKUP_DIR=""; DB="archie"; MODE="scratch"; KEEP_SCRATCH=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)            DB="${2:?--db needs a value}"; shift 2;;
        --into-scratch)  MODE="scratch"; shift;;
        --force)         MODE="force"; shift;;
        --keep-scratch)  KEEP_SCRATCH=1; shift;;
        -h|--help)       usage;;
        -*)              die "unknown flag: $1";;
        *)               [[ -z "$BACKUP_DIR" ]] && BACKUP_DIR="$1" || die "unexpected arg: $1"; shift;;
    esac
done
[[ -n "$BACKUP_DIR" ]] || usage
[[ -d "$BACKUP_DIR" ]] || die "backup dir not found: $BACKUP_DIR"
[[ -d "$BACKUP_DIR/database" ]] || die "no database/ subdir in $BACKUP_DIR (not a Phase 1-6 backup?)"

# ---- DB registry ---------------------------------------------------------------------------
# db -> (prod container, superuser, verify query). archie+wtf share archie_database.
db_container() { case "$1" in archie|wtf) echo archie_database;; creed) echo creed_postgres;; *) die "unknown db: $1";; esac; }
db_user()      { case "$1" in archie|wtf) echo archie;;        creed) echo creed;;          *) die "unknown db: $1";; esac; }
db_verify_sql(){ case "$1" in
                    archie) echo "SELECT count(*) FROM knowledge_base";;
                    wtf)    echo "SELECT count(*) FROM wtf.articles";;
                    creed)  echo "SELECT 1";;
                 esac; }

find_dump() { ls -td "$BACKUP_DIR/database/${1}_"*.dump 2>/dev/null | head -1 || true; }

# Restore <dump> into a throwaway pgvector container, verify, report. Never touches prod.
# Uses explicit cleanup (NOT a RETURN trap — a function-local RETURN trap persists and re-fires
# on the next function's return with an out-of-scope $container under set -u). --shm-size=1g so
# the pgvector HNSW index can build (default 64MB /dev/shm => "No space left on device").
verify_scratch() {
    local db="$1" dump="$2" container="archie_restore_verify_$$_${db}"
    local pc; pc="$(db_container "$db")"
    log "VERIFY ($db): $dump → throwaway container $container"

    # prod baseline (best-effort — archie/wtf live in archie_database; creed in creed_postgres)
    local prod_rows; prod_rows="$(docker exec "$pc" psql -U "$(db_user "$db")" -d "$db" -At -c "$(db_verify_sql "$db")" 2>/dev/null || echo n/a)"

    docker run -d --rm --name "$container" --shm-size=1g -e POSTGRES_PASSWORD=verifyverify \
        -v "$dump":/tmp/dump.dump:ro "$SCRATCH_IMAGE" >/dev/null

    local rc=0 rows="" ready=0 i
    # wait for REAL readiness (pg_isready is fooled by initdb temp-server — see dr_drill.sh)
    for i in $(seq 1 60); do
        if docker exec "$container" psql -U postgres -tAc "SELECT 1" >/dev/null 2>&1; then ready=1; break; fi
        sleep 1
    done

    if [[ "$ready" -ne 1 ]]; then
        log "FAIL ($db): scratch postgres never became ready"; rc=1
    else
        docker exec "$container" psql -U postgres -c "CREATE DATABASE \"$db\";" >/dev/null
        set +e
        docker exec "$container" pg_restore -U postgres -d "$db" --no-owner --no-privileges /tmp/dump.dump 2>&1 | tail -5
        set -e
        rows="$(docker exec "$container" psql -U postgres -d "$db" -At -c "$(db_verify_sql "$db")" 2>/dev/null || echo RESTORE_FAILED)"
        if [[ "$rows" == "RESTORE_FAILED" ]]; then
            log "FAIL ($db): verify query did not run after restore"; rc=1
        elif [[ "$prod_rows" == "n/a" || "$prod_rows" == "0" ]]; then
            log "PASS ($db): restored OK, verify rows=$rows (prod baseline unavailable)"
        else
            local pct; pct="$(awk "BEGIN{d=$prod_rows-$rows; if(d<0)d=-d; printf \"%.4f\", d/$prod_rows*100}")"
            log "PASS ($db): prod=$prod_rows restored=$rows delta=${pct}%"
        fi
    fi

    if [[ "$KEEP_SCRATCH" -eq 0 ]]; then
        docker rm -f "$container" >/dev/null 2>&1 || true
    else
        log "kept scratch container $container (--keep-scratch)"
    fi
    return "$rc"
}

# DESTRUCTIVE prod restore. Requires --force + DR_CONFIRM=RESTORE-NOW.
restore_prod() {
    local db="$1" dump="$2"
    local container user; container="$(db_container "$db")"; user="$(db_user "$db")"
    [[ "${DR_CONFIRM:-}" == "RESTORE-NOW" ]] || die "prod restore of '$db' refused — set DR_CONFIRM=RESTORE-NOW (runbook KB #272184)"
    log "PROD RESTORE ($db) into live $container — DROP+CREATE+pg_restore"
    [[ "$db" == "archie" ]] && log "WARNING: 'archie' is the platform DB — archie_platform should be stopped first."

    # terminate live backends so DROP DATABASE can proceed (maintenance conn on template1)
    docker exec "$container" psql -U "$user" -d template1 -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$db' AND pid<>pg_backend_pid();" >/dev/null
    docker exec "$container" psql -U "$user" -d template1 -c "DROP DATABASE IF EXISTS \"$db\";" >/dev/null
    docker exec "$container" psql -U "$user" -d template1 -c "CREATE DATABASE \"$db\";" >/dev/null
    set +e
    cat "$dump" | docker exec -i "$container" pg_restore -U "$user" -d "$db" --no-owner --no-privileges 2>&1 | tail -8
    local rc=${PIPESTATUS[1]}
    set -e
    local rows; rows="$(docker exec "$container" psql -U "$user" -d "$db" -At -c "$(db_verify_sql "$db")" 2>/dev/null || echo FAILED)"
    [[ "$rows" != "FAILED" ]] || die "prod restore of '$db' did not produce a queryable DB (pg_restore rc=$rc)"
    log "PROD RESTORE OK ($db): verify rows=$rows (pg_restore rc=$rc)"
}

run_one() {
    local db="$1"
    local dump; dump="$(find_dump "$db")"
    [[ -n "$dump" ]] || { log "SKIP ($db): no ${db}_*.dump in $BACKUP_DIR/database/"; return 0; }
    if [[ "$MODE" == "force" ]]; then restore_prod "$db" "$dump"; else verify_scratch "$db" "$dump"; fi
}

DBS=("$DB")
[[ "$DB" == "all" ]] && DBS=(archie wtf creed)

rc_total=0
for d in "${DBS[@]}"; do run_one "$d" || rc_total=1; done
exit "$rc_total"
