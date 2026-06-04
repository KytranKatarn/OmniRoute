#!/bin/bash
# Phase 2 — DR streaming replica of hub archie_database on boston-2.
# Reads replication password from /opt/archie-dr/.replpw (never embedded here).
set -euo pipefail
DR=/opt/archie-dr; DATA=$DR/pgdata; IMG=pgvector/pgvector:pg16
PW="$(cat $DR/.replpw)"
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }

log "pulling $IMG"
docker pull -q "$IMG"
log "replica image version: $(docker run --rm "$IMG" postgres --version)"

# fresh data dir
docker rm -f archie_dr_replica >/dev/null 2>&1 || true
rm -rf "$DATA"; mkdir -p "$DATA"

log "pg_basebackup from hub 100.64.0.4:5432 via slot boston2_replica ..."
docker run --rm --network host -e PGPASSWORD="$PW" -v "$DATA":/pgdata "$IMG" \
  pg_basebackup -h 100.64.0.4 -p 5432 -U replicator -D /pgdata -X stream -S boston2_replica -P
log "basebackup complete ($(du -sh "$DATA" | cut -f1))"

# standby config (password lives in conninfo; mesh+localhost listen only)
cat >> "$DATA/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=100.64.0.4 port=5432 user=replicator password=$PW application_name=boston2_replica'
primary_slot_name = 'boston2_replica'
listen_addresses = '127.0.0.1,100.64.0.10'
EOF
touch "$DATA/standby.signal"
chown -R 999:999 "$DATA"

log "starting replica container on :5433 (read-only standby)"
# NOTE: max_connections etc. must be >= the PRIMARY's (hub sets max_connections=200
# via a command-line flag, NOT in postgresql.conf, so the basebackup'd config has the
# image default 100 -> "insufficient parameter settings" without these overrides).
docker run -d --name archie_dr_replica --restart unless-stopped --network host \
  -v "$DATA":/var/lib/postgresql/data "$IMG" \
  -c port=5433 -c max_connections=200 -c max_worker_processes=8 \
  -c max_wal_senders=10 -c max_locks_per_transaction=64 -c max_prepared_transactions=0 >/dev/null
sleep 8
log "replica recovery status:"
docker exec archie_dr_replica psql -U archie -d archie -tAc "SELECT pg_is_in_recovery();" 2>&1 | head -1 || true
log "replica log tail:"
docker logs --tail 6 archie_dr_replica 2>&1 | sed 's/^/    /'
log "DONE"
