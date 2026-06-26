#!/bin/bash
# ============================================================================
# Phase 6 FAILBACK — mechanism proof on THROWAWAY postgres containers.
# Zero risk to the production brain DB. Proves the exact sequence failback.sh
# uses to "recover data back into Starbase without loss":
#
#   1. A (old primary) streams to B (replica).        [NORMAL]
#   2. A "dies"; B is promoted to primary; new writes land ONLY on B.  [FAILOVER]
#   3. FAILBACK: rebuild A as a replica OF B (basebackup A<-B) so A catches up
#      to B's data (incl. the outage-window write), then switch over: promote A,
#      demote B, re-establish B streaming from A.       [NORMAL again]
#   4. ASSERT: the row written only on B during the outage is present on A,
#      and there is exactly ONE primary at the end.
#
# Uses pgvector/pgvector:pg16 (same image as prod). Temp ports 5599/5600.
#   bash dr/test_failback.sh
# ============================================================================
set -uo pipefail
IMG=pgvector/pgvector:pg16
NETA=dr_fbtest
A=dr_fb_A; B=dr_fb_B          # A = original primary (hub analogue), B = replica (boston-2 analogue)
PA=5599; PB=5600
PW=fbtestpw
SLOT=fb_slot
log(){ echo "[fbtest $(date -u +%H:%M:%S)] $*"; }
cleanup(){ docker rm -f "$A" "$B" >/dev/null 2>&1; docker network rm "$NETA" >/dev/null 2>&1; }
trap cleanup EXIT
cleanup
docker network create "$NETA" >/dev/null

# ---- 1. NORMAL: start primary A, create replication user + slot, seed data ----
log "starting primary A..."
docker run -d --name "$A" --network "$NETA" -e POSTGRES_PASSWORD="$PW" -e POSTGRES_USER=archie \
  -e POSTGRES_DB=archie -p $PA:5432 "$IMG" \
  -c wal_level=replica -c max_wal_senders=5 -c max_replication_slots=5 -c listen_addresses='*' >/dev/null
for i in $(seq 1 30); do docker exec "$A" pg_isready -U archie >/dev/null 2>&1 && break; sleep 1; done
docker exec "$A" psql -U archie -d archie -c "CREATE TABLE dr_marker(id serial primary key, note text, at timestamptz default now());" >/dev/null
docker exec "$A" psql -U archie -d archie -c "INSERT INTO dr_marker(note) VALUES ('seed-on-A-before-outage');" >/dev/null
docker exec "$A" psql -U archie -d archie -c "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '$PW';" >/dev/null
docker exec "$A" psql -U archie -d archie -c "SELECT pg_create_physical_replication_slot('$SLOT');" >/dev/null
docker exec "$A" sh -c "echo 'host replication replicator all md5' >> /var/lib/postgresql/data/pg_hba.conf"
docker exec "$A" psql -U archie -d archie -c "SELECT pg_reload_conf();" >/dev/null

mk_replica(){  # mk_replica <newname> <sourceContainer> <sourceSlot>
  local name="$1" src="$2" slot="$3"
  docker rm -f "$name" >/dev/null 2>&1
  docker run -d --name "$name" --network "$NETA" -e PGPASSWORD="$PW" --entrypoint bash "$IMG" -c "
    rm -rf /var/lib/postgresql/data/* &&
    pg_basebackup -h $src -p 5432 -U replicator -D /var/lib/postgresql/data -X stream -S $slot -P &&
    echo \"primary_conninfo = 'host=$src port=5432 user=replicator password=$PW'\" >> /var/lib/postgresql/data/postgresql.conf &&
    touch /var/lib/postgresql/data/standby.signal &&
    exec docker-entrypoint.sh postgres -c listen_addresses='*'
  " >/dev/null
}

# ---- 1b. B becomes a replica of A and streams the seed ----
log "building B as replica of A..."
mk_replica "$B" "$A" "$SLOT"
for i in $(seq 1 40); do
  r=$(docker exec "$B" psql -U archie -d archie -tAc "SELECT count(*) FROM dr_marker;" 2>/dev/null || echo x)
  [ "$r" = "1" ] && { log "B streaming (seed present)."; break; }
  sleep 1
done
inrec=$(docker exec "$B" psql -U archie -d archie -tAc "SELECT pg_is_in_recovery();" 2>/dev/null)
[ "$inrec" = "t" ] && log "B is a read-only standby. NORMAL established." || { log "FAIL: B not in recovery"; exit 1; }

# ---- 2. FAILOVER: A dies, promote B, write outage-window data ONLY on B ----
log "FAILOVER: stopping A (simulated hub down) + promoting B..."
docker stop "$A" >/dev/null
docker exec "$B" psql -U archie -d archie -c "SELECT pg_promote();" >/dev/null 2>&1 || true
for i in $(seq 1 20); do [ "$(docker exec "$B" psql -U archie -d archie -tAc 'SELECT pg_is_in_recovery();' 2>/dev/null)" = "f" ] && break; sleep 1; done
docker exec "$B" psql -U archie -d archie -c "INSERT INTO dr_marker(note) VALUES ('WRITTEN-ON-B-DURING-OUTAGE');" >/dev/null
log "B promoted to primary; outage-window row written on B."

# ---- 3. FAILBACK: rebuild A as a replica OF B so A gets B's outage write ----
log "FAILBACK step 1: prepare B to feed A (replication user/slot already exist on B via basebackup)..."
docker start "$A" >/dev/null; sleep 4    # A back online (new hub) but its DB is STALE
docker exec "$B" psql -U archie -d archie -c "SELECT pg_create_physical_replication_slot('${SLOT}_back');" >/dev/null 2>&1 || true
docker exec "$B" sh -c "grep -q 'host replication replicator' /var/lib/postgresql/data/pg_hba.conf || echo 'host replication replicator all md5' >> /var/lib/postgresql/data/pg_hba.conf"
docker exec "$B" psql -U archie -d archie -c "SELECT pg_reload_conf();" >/dev/null
log "FAILBACK step 2: rebuild A as a replica of B (A catches up to B incl. the outage write)..."
mk_replica "$A" "$B" "${SLOT}_back"
for i in $(seq 1 40); do
  r=$(docker exec "$A" psql -U archie -d archie -tAc "SELECT count(*) FROM dr_marker WHERE note='WRITTEN-ON-B-DURING-OUTAGE';" 2>/dev/null || echo x)
  [ "$r" = "1" ] && { log "A has caught up — outage write recovered onto A."; break; }
  sleep 1
done

# ---- 3b. SWITCHOVER back to A as primary, B demoted to replica of A ----
log "SWITCHOVER: promote A (back to primary), re-clone B as replica of A..."
docker exec "$A" psql -U archie -d archie -c "SELECT pg_promote();" >/dev/null 2>&1 || true
for i in $(seq 1 20); do [ "$(docker exec "$A" psql -U archie -d archie -tAc 'SELECT pg_is_in_recovery();' 2>/dev/null)" = "f" ] && break; sleep 1; done
docker exec "$A" psql -U archie -d archie -c "SELECT pg_create_physical_replication_slot('${SLOT}_norm');" >/dev/null 2>&1 || true
docker exec "$A" sh -c "grep -q 'host replication replicator' /var/lib/postgresql/data/pg_hba.conf || echo 'host replication replicator all md5' >> /var/lib/postgresql/data/pg_hba.conf"
docker exec "$A" psql -U archie -d archie -c "SELECT pg_reload_conf();" >/dev/null
mk_replica "$B" "$A" "${SLOT}_norm"
sleep 6

# ---- 4. ASSERT: data preserved + exactly one primary ----
echo "----------------------------------------------------------------"
a_has=$(docker exec "$A" psql -U archie -d archie -tAc "SELECT count(*) FROM dr_marker WHERE note='WRITTEN-ON-B-DURING-OUTAGE';" 2>/dev/null)
a_rec=$(docker exec "$A" psql -U archie -d archie -tAc "SELECT pg_is_in_recovery();" 2>/dev/null)
b_rec=$(docker exec "$B" psql -U archie -d archie -tAc "SELECT pg_is_in_recovery();" 2>/dev/null)
a_rows=$(docker exec "$A" psql -U archie -d archie -tAc "SELECT count(*) FROM dr_marker;" 2>/dev/null)
echo "A (final hub) primary?      $([ "$a_rec" = f ] && echo YES || echo NO)   (want YES)"
echo "B (final boston-2) replica? $([ "$b_rec" = t ] && echo YES || echo NO)   (want YES)"
echo "Outage write recovered on A: $([ "$a_has" = 1 ] && echo YES || echo NO)   (want YES)"
echo "Total dr_marker rows on A:   $a_rows   (want 2: seed + outage)"
ok=0
[ "$a_rec" = f ] && [ "$b_rec" = t ] && [ "$a_has" = 1 ] && [ "$a_rows" = 2 ] && ok=1
echo "----------------------------------------------------------------"
[ "$ok" = 1 ] && echo "PHASE 6 FAILBACK MECHANISM: PROVEN ✅ (no data loss, single primary)" || echo "PHASE 6 FAILBACK MECHANISM: FAILED ❌"
exit $((1-ok))
