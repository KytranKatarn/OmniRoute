#!/bin/bash
# Phase 2 — DR streaming replica of hub archie_database on boston-2.
# Reads replication password from /opt/archie-dr/.replpw (never embedded here).
#
# FAIL-SAFE ORDERING (#4994). Two rules, learned the hard way on 2026-07-19 when
# a failed run left NO replica at all:
#   1. Replication auth is validated against the primary BEFORE anything is
#      destroyed. Auth failure now costs ~1s instead of the whole replica.
#      (A1 died on "no pg_hba.conf entry for replication from 100.64.0.10"
#      AFTER the data dir had already been wiped.)
#   2. pg_basebackup lands in a STAGING dir. The live data dir is only replaced
#      once the backup succeeds, and the previous copy is kept as $OLD until the
#      new replica verifiably reaches recovery. A mid-copy failure — e.g. A2's
#      "could not open file ./pg_hba.conf.bak: Permission denied" at 100% of a
#      9.5GB stream — therefore leaves the existing replica untouched.
#
# Exit status is meaningful: the script prints SETUP_REPLICA_RESULT=OK|FAIL on
# every exit path and exits non-zero on failure.
#   ⚠️ Do NOT invoke as `ssh host '... | tail'` — a pipeline returns the exit
#      status of the LAST command, so `| tail` masks a failed run as exit 0
#      (this is how a broken run was mistaken for a good one). Use instead:
#          ssh host '/opt/archie-dr/setup_replica.sh'; echo "EXIT=$?"
set -euo pipefail

DR=/opt/archie-dr
DATA=$DR/pgdata
STAGE=$DR/pgdata.staging
OLD=$DR/pgdata.previous
IMG=pgvector/pgvector:pg16

PRIMARY_HOST=100.64.0.4
PRIMARY_PORT=5432
REPL_USER=replicator
SLOT=boston2_replica
REPLICA_PORT=5433
CONTAINER=archie_dr_replica

PW="$(cat "$DR/.replpw")"

RESULT=FAIL
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
finish() { echo "SETUP_REPLICA_RESULT=$RESULT"; }
trap finish EXIT
fail() {
    log "ERROR: $*"
    exit 1
}

log "pulling $IMG"
docker pull -q "$IMG"
log "replica image version: $(docker run --rm "$IMG" postgres --version)"

# ---------------------------------------------------------------------------
# PRE-FLIGHT — everything below is READ-ONLY. Nothing is destroyed until all
# checks pass, so a failure here leaves the existing replica fully intact.
# ---------------------------------------------------------------------------

log "pre-flight 1/3: replication auth to $PRIMARY_HOST:$PRIMARY_PORT as $REPL_USER"
docker run --rm --network host -e PGPASSWORD="$PW" "$IMG" \
    psql "host=$PRIMARY_HOST port=$PRIMARY_PORT user=$REPL_USER dbname=postgres replication=database connect_timeout=10" \
    -tAc "IDENTIFY_SYSTEM" >/dev/null 2>&1 ||
    fail "replication auth FAILED — the primary rejected $REPL_USER from this host.
       Nothing was deleted; the existing replica is untouched.
       Check pg_hba.conf on the hub allows:
           host replication $REPL_USER 100.64.0.10/32 scram-sha-256
       then reload with: SELECT pg_reload_conf();"
log "  auth OK"

# Slot check is advisory: pg_basebackup -S fails fast on a missing slot, and with
# staging that failure is no longer destructive. Warn rather than block, since the
# replicator role may not be able to read pg_replication_slots on every setup.
log "pre-flight 2/3: replication slot '$SLOT'"
if docker run --rm --network host -e PGPASSWORD="$PW" "$IMG" \
    psql "host=$PRIMARY_HOST port=$PRIMARY_PORT user=$REPL_USER dbname=postgres replication=database connect_timeout=10" \
    -tAc "SELECT 1 FROM pg_replication_slots WHERE slot_name='$SLOT'" 2>/dev/null | grep -q 1; then
    log "  slot present"
else
    log "  WARNING: could not confirm slot '$SLOT' (missing, or not visible to $REPL_USER)"
fi

log "pre-flight 3/3: disk headroom (staging needs a second copy)"
need_kb=$(du -sk "$DATA" 2>/dev/null | cut -f1 || echo 0)
[ -n "$need_kb" ] || need_kb=0
avail_kb=$(df -Pk "$DR" | awk 'NR==2 {print $4}')
# want the new copy + 20% margin; floor at 20GB when there is no existing dir
want_kb=$(((need_kb * 12 / 10) > 20971520 ? (need_kb * 12 / 10) : 20971520))
log "  existing=$((need_kb / 1048576))G available=$((avail_kb / 1048576))G required=$((want_kb / 1048576))G"
[ "$avail_kb" -ge "$want_kb" ] ||
    fail "insufficient disk for a staged basebackup. Nothing was deleted."

# ---------------------------------------------------------------------------
# STAGE — basebackup into a scratch dir. The live replica keeps running.
# ---------------------------------------------------------------------------
rm -rf "$STAGE"
mkdir -p "$STAGE"

log "pg_basebackup from $PRIMARY_HOST:$PRIMARY_PORT via slot $SLOT -> staging ..."
docker run --rm --network host -e PGPASSWORD="$PW" -v "$STAGE":/pgdata "$IMG" \
    pg_basebackup -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPL_USER" -D /pgdata -X stream -S "$SLOT" -P ||
    fail "pg_basebackup FAILED. Staging dir discarded; the existing replica at
       $DATA is untouched and still running.
       If this failed near 100%, check the PRIMARY's data dir for files the
       postgres user cannot read (pg_basebackup streams every file)."
log "basebackup complete ($(du -sh "$STAGE" | cut -f1))"

# standby config (password lives in conninfo; mesh+localhost listen only)
cat >>"$STAGE/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=$PRIMARY_HOST port=$PRIMARY_PORT user=$REPL_USER password=$PW application_name=$SLOT'
primary_slot_name = '$SLOT'
listen_addresses = '127.0.0.1,100.64.0.10'
EOF
touch "$STAGE/standby.signal"
chown -R 999:999 "$STAGE"

# ---------------------------------------------------------------------------
# SWAP — the only destructive window, entered only after a good backup exists.
# ---------------------------------------------------------------------------
log "swapping staging into place (previous copy kept at $OLD)"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
rm -rf "$OLD"
if [ -d "$DATA" ]; then
    mv "$DATA" "$OLD"
fi
mv "$STAGE" "$DATA"

log "starting replica container on :$REPLICA_PORT (read-only standby)"
# NOTE: max_connections etc. must be >= the PRIMARY's (hub sets max_connections=200
# via a command-line flag, NOT in postgresql.conf, so the basebackup'd config has the
# image default 100 -> "insufficient parameter settings" without these overrides).
docker run -d --name "$CONTAINER" --restart unless-stopped --network host \
    -v "$DATA":/var/lib/postgresql/data "$IMG" \
    -c port=$REPLICA_PORT -c max_connections=200 -c max_worker_processes=8 \
    -c max_wal_senders=10 -c max_locks_per_transaction=64 -c max_prepared_transactions=0 >/dev/null
sleep 8

# ---------------------------------------------------------------------------
# VERIFY — a real gate, not a log line. The old code ended this check in
# `|| true` AND omitted -p $REPLICA_PORT, so it could never pass and never
# failed the run either: a dead replica still exited 0.
# ---------------------------------------------------------------------------
log "verifying recovery state"
rec=$(docker exec "$CONTAINER" psql -U archie -d archie -p $REPLICA_PORT -tAc \
    "SELECT pg_is_in_recovery();" 2>/dev/null | tr -d '[:space:]' || true)
if [ "$rec" != "t" ]; then
    log "replica log tail:"
    docker logs --tail 15 "$CONTAINER" 2>&1 | sed 's/^/    /'
    fail "replica did NOT reach recovery (pg_is_in_recovery='$rec').
       The PREVIOUS data dir is preserved at $OLD — no automatic rollback is
       attempted (untested automation on DR is worse than a human decision).
       To roll back manually:
           docker rm -f $CONTAINER
           mv $DATA $DR/pgdata.failed.\$(date +%s)
           mv $OLD $DATA
           # then re-run the 'docker run' block above"
fi
log "  pg_is_in_recovery=t"

log "removing previous copy $OLD"
rm -rf "$OLD"

log "replica log tail:"
docker logs --tail 6 "$CONTAINER" 2>&1 | sed 's/^/    /'
log "NOTE: confirm streaming from the PRIMARY side too — its absence hid a"
log "      diverged fork for 7 days (KB #272172):"
log "      docker exec archie_database psql -U archie -d archie -c \\"
log "        \"SELECT application_name,state,client_addr,replay_lag FROM pg_stat_replication;\""
RESULT=OK
log "DONE"
