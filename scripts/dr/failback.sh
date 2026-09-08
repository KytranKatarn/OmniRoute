#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. DR — PHASE 6 FAILBACK  (return to FULL POWER without data loss)
#
# Run AFTER a real failover where boston-2 became primary and took writes during
# the hub outage. Recovers those writes back onto the hub, then switches the
# primary back to the hub and re-establishes boston-2 as the replica.
#
# Mechanism PROVEN on throwaway DBs by dr/test_failback.sh (green). This is the
# production codification. It is DESTRUCTIVE on the hub DB (rebuilds it from
# boston-2), so it is PHASED + GUARDED and meant to be run step-by-step under
# supervision — NOT fire-and-forget.
#
#   On boston-2:  /opt/archie-dr/failback.sh <phase>
#   phases:  precheck | prep-source | rebuild-hub | switchover | restore-normal | verify
#
# Order: precheck -> prep-source -> rebuild-hub -> (wait caught up) -> switchover
#        -> restore-normal -> verify.  Re-runnable per phase.
# ============================================================================
set -uo pipefail

DR=/opt/archie-dr
IMG=pgvector/pgvector:pg16
HUB_MESH="${HUB_MESH:-100.64.0.4}"; HUB_PG="${HUB_PG:-5432}"
B2_MESH="${B2_MESH:-100.64.0.10}"; B2_PG="${B2_PG:-5433}"
B2_CONTAINER="${B2_CONTAINER:-archie_dr_replica}"
HUB_DB_CONTAINER="${HUB_DB_CONTAINER:-archie_database}"
HUB_SSH="${HUB_SSH:-kytran@$HUB_MESH}"        # hub uses kytran@ not root@ (pubkey in authorized_keys)
FLEET_KEY="${FLEET_KEY:-$DR/.ssh/id_ed25519}"
REPL_USER="${REPL_USER:-replicator}"
BACK_SLOT="${BACK_SLOT:-hub_failback}"         # slot on boston-2 that feeds the hub
PW="$(cat "$DR/.replpw" 2>/dev/null || true)"
log(){ echo "[failback $(date -u +%H:%M:%S)] $*"; }
die(){ log "ABORT: $*"; exit 1; }

# ---- Beacon SELECTIVE upstream flipping (task #5214, ADR-009) ----
# Shared with failover/auto_failback/force_reset so the DR-capable port map
# cannot drift. Fail-safe: loud no-op rather than a blanket sed if not staged.
BEACON_BAK_SUFFIX=".bak-fb"
if [ -f "$DR/beacon_flip.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/beacon_flip.sh"
else
  log "(WARN: $DR/beacon_flip.sh missing — Beacon upstreams will NOT be reverted)"
  beacon_flip_ports(){
    log "  WARN: beacon_flip.sh not staged — skipping Beacon revert for '${3:-?}' (ports ${*:4})."
    return 1
  }
  BEACON_DR_PORTS_ALL=(3000 8086 8095)
fi

# ---- Fleet repoint helpers (task #5278) — ONE node list shared with failover ----
if [ -f "$DR/fleet_repoint.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/fleet_repoint.sh"
else
  log "(WARN: $DR/fleet_repoint.sh missing — fleet repoint-back will use loud no-ops)"
  fleet_repoint_outposts(){
    log "  WARN: fleet_repoint.sh not staged — outposts NOT repointed (manual, per node:"
    log "        ssh root@100.64.0.{5,7,8} /opt/archie-node/repoint.sh ${1:-<target>})"
    return 1
  }
  fleet_kick_starships(){ log "  (fleet_repoint.sh not staged — Starships self-heal in ~2.5 min)"; return 0; }
  fleet_verify_heartbeats(){ log "  WARN: fleet_repoint.sh not staged — heartbeats unverified."; return 1; }
fi

# helpers
b2(){ docker exec "$B2_CONTAINER" psql -U archie -p "$B2_PG" -tAc "$1" 2>/dev/null; }
b2_primary(){ [ "$(b2 'SELECT pg_is_in_recovery();')" = "f" ]; }
hub_reachable(){ timeout 5 bash -c "echo > /dev/tcp/$HUB_MESH/$HUB_PG" 2>/dev/null; }

phase="${1:-}"; [ -n "$phase" ] || die "usage: $0 <precheck|prep-source|rebuild-hub|switchover|restore-normal|verify>"

case "$phase" in

# ----------------------------------------------------------------------------
precheck)
  log "boston-2 primary? (must be YES — a failover must have happened)"
  b2_primary && log "  boston-2 IS primary (RW). Good." || die "boston-2 is NOT primary. Nothing to fail back. (Did failover.sh run?)"
  rows=$(b2 "SELECT count(*) FROM knowledge_base;"); log "  boston-2 knowledge_base rows: ${rows:-?}"
  log "hub Postgres reachable at $HUB_MESH:$HUB_PG?"
  if hub_reachable; then
    log "  YES — the hub is back online."
    log "  ⚠️ SPLIT-BRAIN GUARD: the hub DB must be FENCED (no writes) before rebuild."
    log "     Confirm the hub platform + scheduler are STOPPED so nothing writes the stale hub DB:"
    log "       ssh $HUB_SSH 'cd /mnt/archie_brain && docker compose stop archie_platform archie_scheduler'"
  else
    log "  hub Postgres not reachable yet — bring the hub host + its DB container up first (DB only, platform STOPPED)."
  fi
  log "When the hub DB is up but FENCED (platform/scheduler stopped), run: $0 prep-source"
  ;;

# ----------------------------------------------------------------------------
prep-source)   # make boston-2 able to feed the hub as a replica
  b2_primary || die "boston-2 is not primary; aborting."
  [ -n "$PW" ] || die "missing $DR/.replpw"
  log "ensuring replication slot '$BACK_SLOT' on boston-2..."
  b2 "SELECT pg_create_physical_replication_slot('$BACK_SLOT');" >/dev/null 2>&1 || log "  (slot exists)"
  log "ensuring pg_hba allows the hub ($HUB_MESH) to stream replication..."
  docker exec "$B2_CONTAINER" sh -c "grep -q 'host replication $REPL_USER $HUB_MESH/32' /var/lib/postgresql/data/pg_hba.conf || echo 'host replication $REPL_USER $HUB_MESH/32 md5' >> /var/lib/postgresql/data/pg_hba.conf"
  b2 "SELECT pg_reload_conf();" >/dev/null
  log "boston-2 ready to feed the hub. Next (DESTRUCTIVE): CONFIRM=REBUILD-HUB $0 rebuild-hub"
  ;;

# ----------------------------------------------------------------------------
rebuild-hub)   # DESTRUCTIVE: wipe the stale hub DB, re-clone it FROM boston-2
  [ "${CONFIRM:-}" = "REBUILD-HUB" ] || die "refusing without CONFIRM=REBUILD-HUB (this WIPES the hub DB and re-clones it from boston-2)."
  b2_primary || die "boston-2 is not primary; aborting (never clone from a non-authoritative source)."
  log "discovering the hub DB data dir (host bind mount of $HUB_DB_CONTAINER)..."
  HUB_DATA=$(ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" \
     "docker inspect $HUB_DB_CONTAINER --format '{{range .Mounts}}{{if eq .Destination \"/var/lib/postgresql/data\"}}{{.Source}}{{end}}{{end}}'" 2>/dev/null)
  [ -n "$HUB_DATA" ] || die "could not find hub DB data dir — inspect $HUB_DB_CONTAINER manually."
  log "  hub data dir = $HUB_DATA"
  log "stopping the hub DB container + wiping its data dir, then basebackup FROM boston-2 ($B2_MESH:$B2_PG)..."
  ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "
    set -e
    cd /mnt/archie_brain && docker compose stop $HUB_DB_CONTAINER || docker stop $HUB_DB_CONTAINER || true
    BK=${HUB_DATA}.pre-failback.\$(date +%s); mv '$HUB_DATA' \"\$BK\"; mkdir -p '$HUB_DATA'
    echo '  old hub data moved to '\"\$BK\"' (delete after verifying failback)'
    docker run --rm --network host -e PGPASSWORD='$PW' -v '$HUB_DATA':/pgdata $IMG \
      pg_basebackup -h $B2_MESH -p $B2_PG -U $REPL_USER -D /pgdata -X stream -S $BACK_SLOT -P
    cat >> '$HUB_DATA/postgresql.auto.conf' <<EOF
primary_conninfo = 'host=$B2_MESH port=$B2_PG user=$REPL_USER password=$PW application_name=hub_failback'
primary_slot_name = '$BACK_SLOT'
EOF
    touch '$HUB_DATA/standby.signal'
    chown -R 999:999 '$HUB_DATA'
    cd /mnt/archie_brain && docker compose start $HUB_DB_CONTAINER || docker start $HUB_DB_CONTAINER
  " || die "rebuild-hub failed on the hub side — inspect before retrying."
  log "hub is now a STANDBY streaming from boston-2. Watch it catch up:"
  log "   ssh $HUB_SSH \"docker exec $HUB_DB_CONTAINER psql -U archie -tAc 'SELECT pg_is_in_recovery(), pg_last_wal_replay_lsn();'\""
  log "When lag ~0, run (maintenance window): $0 switchover"
  ;;

# ----------------------------------------------------------------------------
switchover)    # promote hub back to primary, demote boston-2
  log "FENCING boston-2 writes: stop the standby platform + scheduler so no new writes land on boston-2..."
  cd "$DR/platform" 2>/dev/null && docker compose -f docker-compose.standby.yml stop archie_platform_standby archie_scheduler_standby >/dev/null 2>&1 || log "  (standby platform not running / already stopped)"
  log "confirming the hub has caught up (in recovery, lag ~0) BEFORE promoting..."
  inrec=$(ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "docker exec $HUB_DB_CONTAINER psql -U archie -tAc 'SELECT pg_is_in_recovery();'" 2>/dev/null)
  [ "$inrec" = "t" ] || die "hub is not a streaming standby (pg_is_in_recovery=$inrec). Do NOT promote — investigate."
  log "promoting the hub back to PRIMARY..."
  ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "docker exec $HUB_DB_CONTAINER psql -U archie -c 'SELECT pg_promote();'" >/dev/null 2>&1 || true
  sleep 5
  inrec=$(ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "docker exec $HUB_DB_CONTAINER psql -U archie -tAc 'SELECT pg_is_in_recovery();'" 2>/dev/null)
  [ "$inrec" = "f" ] && log "  hub is PRIMARY again." || die "hub did not leave recovery — investigate before restore-normal."
  log "boston-2 is now demoted (its standby platform is stopped). Run: $0 restore-normal"
  ;;

# ----------------------------------------------------------------------------
restore-normal)  # platform + fleet + WTF + DNS back to the hub; boston-2 -> replica again
  log "1) start the real hub platform + scheduler..."
  ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "cd /mnt/archie_brain && docker compose up -d archie_platform archie_scheduler" >/dev/null 2>&1 || log "  (do this manually if it failed)"
  log "2) repoint the global outposts back to the hub ($HUB_MESH)..."
  # Shared list + mechanics: fleet_repoint.sh (#5278 — the same nodes failover
  # touched, iterated by the rollback, then VERIFIED. The 07-27 drill's rollback
  # skipped this and three outposts sat orphaned 9.6h with re-registration
  # loops armed — the KB #270611 storm precondition.)
  fleet_repoint_outposts "$HUB_MESH" || log "   WARN: some outposts not repointed — repoint each on power-up."
  fleet_kick_starships
  log "2v) VERIFY heartbeats resume — a node list is not a rollback until they do..."
  fleet_verify_heartbeats 300 240 \
    || log "   *** FLEET NOT VERIFIED: outposts may still point at boston-2 (#5278). Fix BEFORE closing the incident."
  # 3) WTF DB reverse-repoint: REMOVED — the mirror of failover.sh step 4b, obsolete for
  #    the same reasons. WTF's DB is Citadel-local (@wtf-postgres/wtf), the old outpost-us
  #    path does not exist, and WTF served HTTP 200 straight through the 2026-09-08 hub
  #    outage. Nothing to move back. See failover.sh 4b before re-adding.
  log "3) WTF DB: nothing to repoint — its database is Citadel-local, not the hub's."
  log "4) flip DNS back to the hub (platform A-record)..."
  # Auto-discover the hub's CURRENT public IP (it changes if the hub moved) by
  # asking the hub itself over the mesh — so the flip-back needs NO manual input.
  # Beacon front-door: flip Caddy upstream boston-2 -> hub (reverse of failover 4c).
  # Beacon is addressed by PUBLIC IP, matching failover.sh. The previous default
  # here was the MESH IP (100.64.0.11) with an inline public-IP override on this
  # one call — so steps 4c/4d below silently used the mesh path and would fail
  # during exactly the degraded-mesh conditions a failback runs in.
  # BEACON_HOST is deliberately NOT set here. beacon_flip.sh owns the front-door
  # address AND the BEACON_LOCAL auto-detect (#3245). Re-declaring it here shadowed
  # that default with the Beacon VPS IP removed on 2026-08-28, so every DR ingress
  # step still dialled a host that does not exist — the helper fix could not reach
  # these callers. Override via the ENVIRONMENT if you ever need a different host.
  DR_MESH="${DR_MESH:-100.64.0.10}"

  # Revert EVERY port a failover is allowed to move, in one idempotent pass:
  # platform :3000 + creed :8086 + headscale :8095. Reverting a port that was
  # never flipped is a no-op, so this is complete regardless of how far the
  # failover got — and it replaces the old blanket `sed 's|DR|HUB|g'`, which
  # rewrote the Caddyfile's COMMENTS too (that is why Beacon's header currently
  # claims "DR (boston-2) mesh IP: 100.64.0.4"). Task #5214.
  log "repoint Beacon DR-capable upstreams back to the hub ($HUB_MESH)..."
  # Gated on the HUB actually serving each port (#5225). The only previous
# check was hub POSTGRES :5432, so all three hostnames went back to a hub
# that might not be serving HTTP yet — ADR-009 in reverse. A port the hub
# is not serving is LEFT on DR rather than pointed at a host that cannot
# serve it.
beacon_flip_ports_when_ready "$DR_MESH" "$HUB_MESH" "failback (all DR ports)" "${BEACON_DR_PORTS_ALL[@]}"
# Assert the revert stayed selective, same as failover does.
beacon_verify_selective "$HUB_MESH" 10 || \
  log "  WARN: Beacon does not look selective after failback — check force_reset_to_hub.sh."

# Clear the ADR-012 maintenance splash — the hub is serving these again (#5226).
# Idempotent: a no-op when no splash is in place.
beacon_maintenance_mode off "${BEACON_MAINTENANCE_HOSTS[@]}" \
  || log "  WARN: could not clear the maintenance splash — hub-only hostnames may still show 503."
  log "4b) repoint watch-series agent hub URLs back to the hub ($HUB_MESH)..."
  for product_dir in gov-watch legal-watch what-the-fact; do
    env_file="/opt/archie-products/$product_dir/.env"
    if [ -f "$env_file" ] && grep -q "$DR_MESH:3000" "$env_file"; then
      sed -i.bak-fb "s|$DR_MESH|$HUB_MESH|g" "$env_file" \
        && ( cd "/opt/archie-products/$product_dir" && docker compose up -d >/dev/null 2>&1 ) \
        && log "   $product_dir watch URLs back to hub." \
        || log "   WARN: $product_dir reverse-repoint failed (manual: sed $env_file $DR_MESH->$HUB_MESH, docker compose up -d)"
    fi
  done

  log "4c) stop Headscale DR standby + revert Beacon mesh entry back to hub..."
  HS_DIR="$DR/headscale"
  [ -f "$HS_DIR/docker-compose.headscale-dr.yml" ] \
    && ( cd "$HS_DIR" && docker compose -f docker-compose.headscale-dr.yml down >/dev/null 2>&1 ) \
    && log "   Headscale DR stopped." \
    || log "   (Headscale DR was not running — nothing to stop)"
  # (Beacon's mesh. :8095 entry was already reverted in step 4 above, together
  #  with every other DR-capable port, so there is nothing to flip here.)
  log "4d) stop C.R.E.E.D. on boston-2 + revert Beacon :8086 back to hub..."
  CREED_DIR=/opt/archie-products/creed
  [ -f "$CREED_DIR/docker-compose.yml" ] \
    && ( cd "$CREED_DIR" && docker compose down >/dev/null 2>&1 ) \
    && log "   CREED stopped on boston-2." \
    || log "   (CREED was not running on boston-2 — nothing to stop)"
  # (Beacon's creed. / api.creed-ai.org :8086 entries were already reverted in
  #  step 4 above, together with every other DR-capable port.)

  # NOTE (task #3787): platform.kytranempowerment.com DNS STAYS on the Beacon
  # front-door (2.25.170.252) — it was never flipped off Beacon (see failover.sh),
  # so there is nothing to flip back here. Failback is handled by reverting Beacon's
  # Caddy upstream boston-2->hub (step 6 of auto_failback.sh / the Beacon revert).
  # The old dns_flip_back.sh pointed platform at the hub's RAW IP (bypassing Beacon)
  # and auto_failback never called it at all — that asymmetry stranded platform on
  # boston-2. dns_flip_back.sh is retained ONLY for a manual Beacon-down emergency.
  log "   platform DNS stays on the front door (Citadel 2.25.133.122); failback handled by its upstream revert."
  log "5) re-establish boston-2 as a REPLICA of the hub (the normal direction):"
  log "     ON BOSTON-2: $DR/setup_replica.sh   (re-clones boston-2 from the hub; resumes streaming)"
  log "Then run: $0 verify"
  ;;

# ----------------------------------------------------------------------------
verify)
  log "hub is primary (single primary)?"
  hubrec=$(ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "docker exec $HUB_DB_CONTAINER psql -U archie -tAc 'SELECT pg_is_in_recovery();'" 2>/dev/null)
  [ "$hubrec" = "f" ] && log "  hub primary: YES" || log "  hub primary: NO ($hubrec) — investigate"
  log "boston-2 is a replica again (streaming)?"
  b2rec=$(b2 'SELECT pg_is_in_recovery();')
  [ "$b2rec" = "t" ] && log "  boston-2 replica: YES" || log "  boston-2 replica: NO ($b2rec) — re-run setup_replica.sh"
  log "hub knowledge_base rows (should match boston-2's pre-failback count):"
  ssh -i "$FLEET_KEY" -o BatchMode=yes "$HUB_SSH" "docker exec $HUB_DB_CONTAINER psql -U archie -d archie -tAc 'SELECT count(*) FROM knowledge_base;'" 2>/dev/null | sed 's/^/  hub: /'
  log "If hub=primary + boston-2=replica + row counts good: FAILBACK COMPLETE. Delete the *.pre-failback.* dir on the hub."
  ;;

*) die "unknown phase '$phase'";;
esac
