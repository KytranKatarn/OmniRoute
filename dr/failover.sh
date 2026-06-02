#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. DR FAILOVER — run ON boston-2 (the DR node) when the Starbase
# (hub, mesh 100.64.0.4) is DOWN. Promotes the local replica to a read-write
# primary and starts the standby platform against it.
#
# SELF-CONTAINED: depends on NOTHING from the hub. Run from anywhere:
#     ssh root@2.25.133.122 /opt/archie-dr/failover.sh [--force]
#
# Covers DR plan Phase 4 (promote + start + verify). Public ingress / DNS flip
# is Phase 5 (see dns_flip note at the end). Idempotent-ish; split-brain guarded.
# ============================================================================
set -uo pipefail
DR=/opt/archie-dr
HUB_MESH=100.64.0.4
FORCE="${1:-}"
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }

# ---- SAFETY: confirm the hub is really down (split-brain guard) ----
log "Split-brain guard: checking the hub is actually down ($HUB_MESH:5432)..."
if timeout 5 bash -c "echo > /dev/tcp/$HUB_MESH/5432" 2>/dev/null; then
  if [ "$FORCE" != "--force" ]; then
    log "ABORT: hub Postgres is REACHABLE — the hub appears UP."
    log "Promoting now would create a SPLIT-BRAIN (two primaries). Refusing."
    log "If you are CERTAIN the hub is dead, re-run: $0 --force"
    exit 1
  fi
  log "--force given: proceeding despite hub reachability (YOU asserted hub is dead)."
fi

# ---- 1. PROMOTE replica -> primary (read-write) ----
log "Promoting the replica (archie_dr_replica :5433) to PRIMARY..."
docker exec archie_dr_replica pg_ctl promote -D /var/lib/postgresql/data >/dev/null 2>&1 \
  || docker exec archie_dr_replica psql -U archie -p 5433 -tAc "SELECT pg_promote();" >/dev/null 2>&1
for i in $(seq 1 10); do
  sleep 3
  INREC=$(docker exec archie_dr_replica psql -U archie -p 5433 -tAc "SELECT pg_is_in_recovery();" 2>/dev/null)
  [ "$INREC" = "f" ] && break
done
if [ "${INREC:-}" = "f" ]; then log "Replica promoted to PRIMARY (read-write)."; else
  log "ERROR: replica did NOT leave recovery (pg_is_in_recovery=$INREC). Aborting before starting platform."; exit 2; fi

# ---- 2. START the standby platform (now points at the RW DB) ----
log "Starting standby platform + scheduler (archie_platform_standby + archie_scheduler_standby)..."
cd "$DR/platform" && docker compose -f docker-compose.standby.yml up -d archie_platform_standby archie_scheduler_standby >/dev/null 2>&1

# ---- 3. VERIFY platform serves + DB is writable ----
log "Verifying platform serves /login + DB accepts writes..."
H=ERR
for i in $(seq 1 8); do
  sleep 10
  H=$(python3 -c "import urllib.request as u
try: print(u.urlopen('http://127.0.0.1:3000/login',timeout=8).getcode())
except Exception: print('ERR')" 2>/dev/null)
  log "  /login http=$H"
  [ "$H" = "200" ] && break
done
WOK=$(docker exec archie_dr_replica psql -U archie -d archie -p 5433 -tAc \
  "CREATE TABLE IF NOT EXISTS _dr_failover_marker(at timestamptz default now()); INSERT INTO _dr_failover_marker DEFAULT VALUES; SELECT 'WRITE_OK';" 2>/dev/null | tail -1)
log "  DB write check: ${WOK:-FAILED}"

# ---- 4. FLEET REPOINT: point surviving nodes at boston-2 (Phase 5b) ----
# Each node's hub URL is a BAKED container env var → repoint.sh RECREATES the
# sync container (a `docker restart` ignores --env-file). KB #270232. Mesh IP
# only — MagicDNS dies with the hub. Non-fatal: failover proceeds per-node.
DR_MESH=100.64.0.10
FLEET_KEY="$DR/.ssh/id_ed25519"
# Surviving global outposts (root@, /opt/archie-node). LAN Starships die with a
# Montreal-site outage. outpost-us (kytran@, /opt/archie-outpost) = TODO (divergent path).
FLEET_NODES=( "root@100.64.0.5" "root@100.64.0.7" "root@100.64.0.8" )
log "Repointing surviving fleet nodes -> boston-2 ($DR_MESH)..."
if [ -f "$FLEET_KEY" ]; then
  for node in "${FLEET_NODES[@]}"; do
    if ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$node" \
         "/opt/archie-node/repoint.sh $DR_MESH" >/dev/null 2>&1; then
      log "  repointed $node"
    else
      log "  WARN: could not repoint $node (skipping)"
    fi
  done
else
  log "  WARN: $FLEET_KEY missing — cannot repoint fleet (stage the DR key; DR plan 5b)."
fi

# ---- 5. PUBLIC INGRESS (Caddy) + DNS FLIP (Phase 5) ----
log "Starting public HTTPS ingress (Caddy)..."
if [ -f "$DR/ingress/docker-compose.caddy.yml" ]; then
  ( cd "$DR/ingress" && docker compose -f docker-compose.caddy.yml up -d caddy >/dev/null 2>&1 ) \
    && log "Caddy up (auto-provisions LE cert once DNS points here)." \
    || log "WARN: Caddy failed to start — platform still serves on 127.0.0.1:3000."
else
  log "WARN: Caddy ingress not staged — platform serves on 127.0.0.1:3000 only."
fi
log "Flipping public DNS (platform.kytranempowerment.com -> boston-2)..."
if [ -x "$DR/dns_flip.sh" ] && [ -f "$DR/.hostinger_token" ]; then
  "$DR/dns_flip.sh" 2>&1 | sed 's/^/    /'
else
  log "WARN: DNS flip NOT run (missing $DR/.hostinger_token). MANUAL: point platform A-record -> 2.25.133.122."
fi

if [ "$H" = "200" ] && [ "${WOK:-}" = "WRITE_OK" ]; then
  log "✅ FAILOVER COMPLETE. Platform LIVE on boston-2 (degraded: no GPU; cloud/CPU inference)."
  log "   Remember Phase 5 (public ingress) for external users, and FAILBACK when the hub returns."
else
  log "⚠️ FAILOVER PARTIAL: login=$H write=${WOK:-FAILED}. Investigate (logs: docker logs archie_platform_standby)."
fi
