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

# ---- FIX6 (DR remediation): guard against an ACCIDENTAL interactive failover ----
# A wholesale failover flips PRODUCTION DNS + promotes the DR replica — never run
# it by reflex. The Phase-7 watchdog and cron invoke this NON-interactively (no
# TTY), so they pass straight through and the automation is unaffected. Only a
# human typing the command at a terminal is stopped, and only until they opt in
# explicitly. For a drill, promote the replica + start the standby by hand instead.
if [ -t 0 ] && [ "$FORCE" != "--force" ] && [ "${DR_CONFIRM:-}" != "FAILOVER-NOW" ]; then
  echo "REFUSING interactive wholesale failover — this flips PRODUCTION DNS and" >&2
  echo "promotes the DR replica to primary." >&2
  echo "  If you truly mean it:  DR_CONFIRM=FAILOVER-NOW $0   (or: $0 --force)" >&2
  exit 3
fi

# ---- Telegram alert helper (shared, sourced — NOT in git: see tg_notify.sh) ----
# tg_notify() now lives in $DR/tg_notify.sh so failover.sh AND the Phase 7
# watchdog use ONE implementation (DRY). DR + log() are defined above, so the
# helper resolves correctly. Fail-safe: if the shared file is missing (e.g. not
# yet deployed), define a no-op stub so failover NEVER aborts over a missing
# alert helper — alerting is best-effort, promotion is not.
if [ -f "$DR/tg_notify.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/tg_notify.sh"
else
  log "  (WARN: $DR/tg_notify.sh missing — Telegram alerts disabled, continuing)"
  tg_notify(){ :; }
fi

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

# ---- 0. ALERT: announce failover is starting (before anything irreversible) ----
tg_notify $'⚠️ <b>A.R.C.H.I.E. DR FAILOVER STARTING</b>\nThe hub (mesh 100.64.0.4) looks DOWN. Promoting the boston-2 replica to primary and starting the standby platform. You will get a follow-up message when it is live (or if it only partially comes up).'

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
# Surviving global outposts (root@, /opt/archie-node).
# LAN Starships (100.64.0.3 / .6, Famil@ SSH, Windows Docker Desktop):
#   NOT repointed here — they self-heal via node_sync.py DR auto-failover:
#   after 5 consecutive heartbeat failures (~2.5 min) node_sync.py switches
#   hub_url to DR_HUB_URL (default: http://100.64.0.10:3000) and re-registers
#   on boston-2. Auto-fails-back when primary recovers for 3 checks. No SSH
#   needed. Requires node_sync.py v3.0.0+ (docker-compose.node.yml image).
# outpost-us (kytran@, /opt/archie-outpost): watch-product URLs handled in 4d above.
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
# Starship nodes (Windows, Famil@ SSH via mesh; firewall rule added 2026-06-04;
# DR_HUB_URL=100.64.0.10:3000 baked in compose). Force-recreate sync container
# so node_sync immediately reads DR_HUB_URL instead of waiting 2.5 min.
if [ -f "$FLEET_KEY" ]; then
  for starship_mesh in "100.64.0.3" "100.64.0.6"; do
    if ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "Famil@$starship_mesh" \
         "docker compose -f C:\\archie-node\\docker-compose.yml up -d --force-recreate --no-deps sync" >/dev/null 2>&1; then
      log "  Starship $starship_mesh: node_sync restarted (DR_HUB_URL=boston-2 active)"
    else
      log "  WARN: Starship $starship_mesh unreachable — self-healing fires in ~2.5 min"
    fi
  done
fi

# ---- 4b. WTF: repoint its DB to boston-2 so it keeps SERVING + SAVING in DR ----
# WTF's data is the hub `wtf` DATABASE (NOT the empty archie.wtf schema — KB #270304),
# now live on boston-2 at $DR_MESH:5433. WTF runs on outpost-boston (kytran@, mesh
# 100.64.0.2). Flip WTF_DATABASE_URL host hub->boston-2 then `up -d` (an env change
# needs up -d, not restart). Non-fatal — a WTF repoint failure never aborts failover.
WTF_HOST="${WTF_HOST:-kytran@100.64.0.2}"
WTF_DIR="${WTF_DIR:-/opt/archie-products/what-the-fact}"
if [ -f "$FLEET_KEY" ]; then
  log "Repointing WTF DB -> boston-2 ($DR_MESH:5433) on $WTF_HOST ..."
  if ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$WTF_HOST" \
       "cd '$WTF_DIR' && sed -i.bak-dr 's#@100.64.0.4/wtf#@$DR_MESH:5433/wtf#' .env && docker compose up -d" >/dev/null 2>&1; then
    log "  WTF repointed — ingest keeps saving to the boston-2 wtf DB."
  else
    log "  WARN: WTF repoint failed (manual: on $WTF_HOST edit $WTF_DIR/.env DB host -> $DR_MESH:5433, then docker compose up -d)."
  fi
fi

# ---- 4c. BEACON front-door: flip its Caddy upstream hub -> boston-2 so the public
# DNS that points at Beacon keeps reaching the platform (now the DR standby). Non-fatal. ----
BEACON_HOST="${BEACON_HOST:-root@2.25.170.252}"  # public IP — mesh may be down during failover
DR_MESH="${DR_MESH:-100.64.0.10}"
if [ -f "$FLEET_KEY" ]; then
  log "Repointing Beacon front-door Caddy upstream -> boston-2 ($DR_MESH)..."
  if ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$BEACON_HOST" \
       "sed -i.bak-dr 's|$HUB_MESH|$DR_MESH|g' /etc/caddy/Caddyfile && caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1 && systemctl reload caddy" >/dev/null 2>&1; then
    log "  Beacon front-door now points at the boston-2 standby."
  else
    log "  WARN: Beacon repoint failed (manual: on Beacon sed Caddyfile $HUB_MESH->$DR_MESH + systemctl reload caddy)."
  fi
fi

# ---- 4d. Watch-series agents: repoint *_HUB_URL / BRIDGE_URL hub -> boston-2 DRP ----
# gov-watch / legal-watch / what-the-fact each dispatch AI work (bias scoring,
# procurement analysis, etc.) via GOV_BRIDGE_URL / CROSS_WATCH_HUB_URL / WTF_HUB_URL
# pointing at the hub (100.64.0.4:3000). Flip to the local DRP platform so agent
# dispatch keeps working during the outage. Files are LOCAL to boston-2 — no SSH.
log "Repointing watch-series agent hub URLs -> boston-2 DRP ($DR_MESH)..."
watch_flip=0
for product_dir in gov-watch legal-watch what-the-fact; do
  env_file="/opt/archie-products/$product_dir/.env"
  if [ -f "$env_file" ] && grep -q "100.64.0.4:3000" "$env_file"; then
    if sed -i.bak-dr "s|100.64.0.4|$DR_MESH|g" "$env_file" 2>/dev/null; then
      ( cd "/opt/archie-products/$product_dir" && docker compose up -d >/dev/null 2>&1 ) \
        && log "  $product_dir: hub URLs flipped + containers restarted" \
        || log "  WARN: $product_dir restart failed (env flipped — manual: docker compose up -d)"
      watch_flip=$((watch_flip+1))
    else
      log "  WARN: $product_dir sed failed (manual: sed $env_file 100.64.0.4->$DR_MESH, docker compose up -d)"
    fi
  fi
done
[ "$watch_flip" -gt 0 ] \
  && log "  $watch_flip watch products repointed to boston-2 DRP." \
  || log "  (no watch .env files contained hub URLs — skipping)"

# ---- 4e. C.R.E.E.D.: restore latest DB dump + start on boston-2 + flip Beacon :8086 ----
# Pre-condition: backup_triage.sh nightly rsyncs /mnt/archie_brain/kytran-creed/ ->
# /opt/archie-products/creed/ on this node (excluding data/ so postgres is not overwritten).
# Non-fatal: if source not staged or dump missing, CREED stays down but failover continues.
CREED_DIR=/opt/archie-products/creed
log "Starting C.R.E.E.D. on boston-2 (DR mode)..."
if [ -f "$CREED_DIR/docker-compose.yml" ]; then
    # Start postgres first, wait for healthy (up to 60s)
    ( cd "$CREED_DIR" && docker compose up -d postgres >/dev/null 2>&1 )
    for i in $(seq 1 12); do
        docker exec creed_postgres pg_isready -U creed >/dev/null 2>&1 && break || sleep 5
    done
    # Restore latest CREED dump (custom format, piped via stdin)
    CREED_DUMP=$(ls -t "$DR/backups/"*_Daily_Triage/database/creed_*.dump 2>/dev/null | head -1)
    if [ -n "$CREED_DUMP" ]; then
        cat "$CREED_DUMP" | docker exec -i creed_postgres \
            pg_restore -U creed -d creed --clean --if-exists --no-owner >/dev/null 2>&1 \
            && log "  CREED DB restored from $(basename "$CREED_DUMP")" \
            || log "  WARN: CREED DB restore failed — CREED will start with existing/empty DB"
    else
        log "  WARN: no CREED DB dump found in $DR/backups/ — starting with existing/empty DB"
    fi
    ( cd "$CREED_DIR" && docker compose up -d >/dev/null 2>&1 ) \
        && log "  CREED started on boston-2 (:8086)" \
        || log "  WARN: CREED docker compose up failed on boston-2"
    # Flip Beacon creed entry hub:8086 -> boston-2:8086
    if [ -f "$FLEET_KEY" ]; then
        ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$BEACON_HOST" \
            "sed -i.bak-dr 's|http://$HUB_MESH:8086|http://$DR_MESH:8086|' /etc/caddy/Caddyfile \
             && caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
             && systemctl reload caddy" >/dev/null 2>&1 \
            && log "  Beacon creed.kytranempowerment.com -> boston-2 ($DR_MESH:8086)" \
            || log "  WARN: Beacon creed flip failed (manual: sed Caddyfile $HUB_MESH:8086->$DR_MESH:8086 + reload)"
    fi
else
    log "  WARN: CREED not staged at $CREED_DIR (run backup_triage.sh to pre-stage) — skipping"
fi

# ---- 4f. Headscale DR standby — mesh control plane continues for long outages ----
# The mesh DATA PLANE (WireGuard) keeps working without Headscale; standby is
# needed only for new node enrollments and key rotation during extended outages.
# Latest backup (headscale_*.tar.gz) ships here nightly via backup_triage.sh.
# Beacon mesh.kytranempowerment.com entry is flipped hub:8095 -> boston-2:8095.
HS_DIR="$DR/headscale"
log "Starting Headscale DR standby (mesh control plane)..."
if [ -d "$HS_DIR" ] && [ -f "$HS_DIR/docker-compose.headscale-dr.yml" ]; then
    # Extract latest Headscale backup into the data dir
    HS_DUMP=$(ls -t "$DR/backups/"*_Daily_Triage/database/headscale_*.tar.gz 2>/dev/null | head -1)
    mkdir -p "$HS_DIR/data"
    if [ -n "$HS_DUMP" ]; then
        tar -xzf "$HS_DUMP" -C "$HS_DIR/data" 2>/dev/null \
            && log "  Headscale data restored from $(basename "$HS_DUMP")" \
            || log "  WARN: Headscale data extraction failed — starting with empty DB"
    else
        log "  WARN: no Headscale backup found — starting with empty DB (new enrollments possible, existing nodes from cache)"
    fi
    ( cd "$HS_DIR" && docker compose -f docker-compose.headscale-dr.yml up -d >/dev/null 2>&1 ) \
        && log "  Headscale DR started on boston-2 (:8095)" \
        || log "  WARN: Headscale DR failed to start — mesh DATA PLANE still works from node cache"
    # Flip Beacon mesh entry hub:8095 -> boston-2:8095
    if [ -f "$FLEET_KEY" ]; then
        ssh -i "$FLEET_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "$BEACON_HOST" \
            "sed -i.bak-dr 's|http://$HUB_MESH:8095|http://$DR_MESH:8095|' /etc/caddy/Caddyfile \
             && caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
             && systemctl reload caddy" >/dev/null 2>&1 \
            && log "  Beacon mesh.kytranempowerment.com -> boston-2 ($DR_MESH:8095)" \
            || log "  WARN: Beacon mesh flip failed (manual: sed Caddyfile $HUB_MESH:8095->$DR_MESH:8095 + reload)"
    fi
else
    log "  WARN: Headscale DR not staged at $HS_DIR (run: rsync scripts/dr/headscale/ boston-2:/opt/archie-dr/headscale/) — skipping"
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

# ---- verify the DR SCHEDULER actually came up (background jobs, not just the API) ----
# Without this, a silently-dead scheduler means ingest/embedding/fleet-health/
# delegate-worker/node-auto-provision are all stalled while failover reports success.
SCHED="DOWN"
if docker ps --filter name=archie_scheduler_standby --filter status=running \
     --format '{{.Names}}' 2>/dev/null | grep -q archie_scheduler_standby; then
  sleep 3   # let the agent loop register its jobs
  if docker logs archie_scheduler_standby 2>&1 | grep -q "Agent loop started with"; then
    SCHED="UP"
  else
    SCHED="STARTED_NO_JOBS"
  fi
fi
log "DR scheduler (archie_scheduler_standby): $SCHED"

if [ "$H" = "200" ] && [ "${WOK:-}" = "WRITE_OK" ]; then
  log "   Remember Phase 5 (public ingress) for external users, and FAILBACK when the hub returns."
  if [ "$SCHED" = "UP" ]; then
    log "✅ FAILOVER COMPLETE. Platform + scheduler LIVE on boston-2 (degraded: no GPU; cloud/CPU inference)."
    tg_notify $'✅ <b>A.R.C.H.I.E. DR FAILOVER COMPLETE</b>\nPlatform + background scheduler are LIVE on boston-2 (degraded: no GPU — CPU/cloud inference). External access needs the public-ingress/DNS step. Remember to FAILBACK once the hub returns.'
  else
    log "⚠️ FAILOVER: platform LIVE but SCHEDULER=$SCHED — background jobs may NOT be running. Check: docker logs archie_scheduler_standby"
    tg_notify "⚠️ <b>A.R.C.H.I.E. DR FAILOVER — PLATFORM UP, SCHEDULER $SCHED</b>
The API is live on boston-2, but the background job scheduler did not verify. Recurring work (ingest, embedding, fleet health, delegate worker, node auto-provision) may be stalled. On boston-2: docker logs archie_scheduler_standby"
  fi
else
  log "⚠️ FAILOVER PARTIAL: login=$H write=${WOK:-FAILED} scheduler=$SCHED. Investigate (logs: docker logs archie_platform_standby)."
  tg_notify "⚠️ <b>A.R.C.H.I.E. DR FAILOVER PARTIAL</b>
login=$H, db_write=${WOK:-FAILED}, scheduler=$SCHED. The promote/start step did not fully verify. Investigate on boston-2: docker logs archie_platform_standby"
fi
