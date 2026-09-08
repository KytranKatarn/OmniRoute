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

# ---- Beacon SELECTIVE upstream flipping (task #5214, ADR-009) ----
# One shared implementation for failover/failback/auto_failback/force_reset, so
# the DR-capable service map cannot drift between them. See beacon_flip.sh for
# why a blanket sed over Beacon's Caddyfile is an outage generator.
# Fail-safe: if the helper is not staged, DEFINE LOUD NO-OPS rather than falling
# back to the old blanket sed — skipping the flip costs one service, blanket-
# flipping costs twenty.
if [ -f "$DR/beacon_flip.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/beacon_flip.sh"
else
  log "  (WARN: $DR/beacon_flip.sh missing — Beacon upstreams will NOT be flipped)"
  log "         deploy it: scp scripts/dr/beacon_flip.sh root@100.64.0.10:$DR/"
  beacon_flip_ports(){
    log "  WARN: beacon_flip.sh not staged — skipping Beacon flip for '${3:-?}' (ports ${*:4})."
    log "        manual: on Beacon sed 'reverse_proxy http://${1}:<port>' -> '${2}:<port>' + reload caddy"
    return 1
  }
  beacon_verify_selective(){ log "  Beacon verify: SKIPPED (helper not staged)."; return 0; }
  dr_service_listening(){ log "  WARN: readiness probe unavailable (helper not staged) for ${3:-?}."; return 1; }
  beacon_flip_ports_when_ready(){ log "  WARN: readiness-gated flip unavailable (helper not staged)."; return 1; }
  beacon_maintenance_mode(){ log "  WARN: maintenance splash unavailable (helper not staged)."; return 1; }
  BEACON_MAINTENANCE_HOSTS=()
  BEACON_DR_PORT_PLATFORM=3000
  BEACON_DR_PORT_CREED=8086
  BEACON_DR_PORT_HEADSCALE=8095
fi
# The "is it really serving?" probe (dr_service_listening) now lives in
# beacon_flip.sh so failover / failback / auto_failback / force_reset share ONE
# rule that cannot drift between them (task #5225). HOST IS A PARAMETER:
# failover asks about $DR_MESH, failback asks about $HUB_MESH.
# Defining a second copy here would SHADOW the shared one with a different
# signature — beacon_flip_ports_when_ready() passes three args and would
# silently treat the host as a port.

# ---- Fleet repoint helpers (task #5278) — ONE node list, shared ----
# The node list + repoint/verify mechanics live in fleet_repoint.sh so
# failback.sh and force_reset_to_hub.sh can iterate the SAME nodes this script
# touches. The 2026-07-27 drill proved the alternative: the list lived only
# here, the rollback couldn't repoint what it didn't know about, and three
# outposts sat orphaned for 9.6h. Fail-safe: LOUD no-ops, never silent skips.
if [ -f "$DR/fleet_repoint.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/fleet_repoint.sh"
else
  log "  (WARN: $DR/fleet_repoint.sh missing — fleet will NOT be repointed)"
  log "         deploy it: scp scripts/dr/fleet_repoint.sh root@100.64.0.10:$DR/"
  fleet_repoint_outposts(){
    log "  WARN: fleet_repoint.sh not staged — outposts NOT repointed (manual, per node:"
    log "        ssh root@100.64.0.{5,7,8} /opt/archie-node/repoint.sh ${1:-<target>})"
    return 1
  }
  fleet_kick_starships(){ log "  (fleet_repoint.sh not staged — Starships self-heal in ~2.5 min)"; return 0; }
  fleet_verify_heartbeats(){ log "  WARN: fleet_repoint.sh not staged — heartbeats unverified."; return 1; }
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

# ---- SAFETY: heartbeat veto (cont-102, KB #276817) — hub may be MESH-ISOLATED but ALIVE ----
# The split-brain guard above probes the hub MESH IP (:5432), which is BLIND to a
# mesh-only outage (the hub drops off the mesh but its DB is fine — the cont-101
# false failover). The hub posts $HEARTBEAT_FILE over a mesh-INDEPENDENT public
# path when its local DB is healthy; a FRESH one means promoting now would
# split-brain a LIVE hub DB. Independent backstop for manual/cron invocations.
HEARTBEAT_FILE="${HEARTBEAT_FILE:-$DR/.hub_heartbeat}"
HEARTBEAT_MAX_AGE="${HEARTBEAT_MAX_AGE:-300}"
_hb_fresh(){
  [ -f "$HEARTBEAT_FILE" ] || return 1
  local line ts db age
  line="$(cat "$HEARTBEAT_FILE" 2>/dev/null)" || return 1
  ts="$(printf '%s\n' "$line" | sed -n 's/.*ts=\([0-9][0-9]*\).*/\1/p')"
  db="$(printf '%s\n' "$line" | sed -n 's/.*db=\([a-zA-Z][a-zA-Z]*\).*/\1/p')"
  [ -n "$ts" ] && [ "$db" = "ok" ] || return 1
  age=$(( $(date +%s) - ts )); [ "$age" -ge 0 ] && [ "$age" -le "$HEARTBEAT_MAX_AGE" ]
}
if _hb_fresh; then
  log "Hub heartbeat is FRESH (DB healthy, posted over the public path) — hub is mesh-isolated, NOT dead."
  if [ "$FORCE" != "--force" ]; then
    log "ABORT: refusing to promote behind a LIVE hub DB (split-brain). If the hub is truly dead, re-run: $0 --force"
    tg_notify $'🛰️ <b>DR FAILOVER ABORTED — hub is ALIVE (mesh-isolated)</b>\nThe hub is posting a live heartbeat (DB healthy) over the public path. Promoting would split-brain a live DB. NOT promoting. Fix the mesh, or re-run with --force if you are certain the hub DB is dead.'
    exit 1
  fi
  log "--force given: proceeding despite a fresh hub heartbeat (YOU asserted hub DB is dead)."
fi

# ---- SAFETY: replica-freshness guard (cont-102) — never promote STALE data ----
# cont-101 promoted a replica that had been a stale/forked standby for ~7 days
# (#272172 data loss). Require the replica to be an IN-RECOVERY standby that
# replayed a transaction within REPLICA_MAX_LAG. We deliberately do NOT require a
# live WAL receiver: when the hub (primary) is genuinely dead the receiver drops,
# so replay-lag recency is the correct "was it caught up" signal. Respects --force.
REPLICA_MAX_LAG="${REPLICA_MAX_LAG:-1800}"   # max replay lag (s) tolerated at promote time
log "Replica-freshness guard: archie_dr_replica must be an in-recovery standby caught up within ${REPLICA_MAX_LAG}s..."
_rep=$(docker exec archie_dr_replica psql -U archie -d archie -p 5433 -tAc \
  "SELECT (CASE WHEN pg_is_in_recovery() THEN 't' ELSE 'f' END) || '|' || COALESCE(round(EXTRACT(EPOCH FROM (now()-pg_last_xact_replay_timestamp())))::text,'na')" 2>/dev/null | tr -d '[:space:]')
_inrec="${_rep%%|*}"; _lag="${_rep#*|}"
log "  in_recovery=$_inrec replay_lag_s=$_lag (max=$REPLICA_MAX_LAG)"
_fresh_ok=1
[ "$_inrec" = "t" ] || _fresh_ok=0
case "$_lag" in ''|na) _fresh_ok=0 ;; *) [ "$_lag" -le "$REPLICA_MAX_LAG" ] 2>/dev/null || _fresh_ok=0 ;; esac
if [ "$_fresh_ok" -ne 1 ]; then
  if [ "$FORCE" != "--force" ]; then
    log "ABORT: replica is NOT a fresh in-recovery standby (in_recovery=$_inrec, replay_lag=${_lag}s). Refusing to promote STALE/diverged data."
    tg_notify "🟥 <b>DR FAILOVER ABORTED — replica not fresh</b>
boston-2 replica: in_recovery=$_inrec, replay_lag=${_lag}s (max ${REPLICA_MAX_LAG}s). Promoting would risk STALE/diverged data (the cont-101 pattern). NOT promoting. Rebuild it (setup_replica.sh) or re-run with --force to accept the risk."
    exit 1
  fi
  log "--force given: promoting despite a non-fresh replica (YOU accepted possible data loss)."
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
# Node list + mechanics live in fleet_repoint.sh (ONE list shared with
# failback.sh and force_reset_to_hub.sh — task #5278: a rollback must be able
# to iterate the same nodes a failover touched). Baked-env rationale (repoint.sh
# RECREATES the sync container; `docker restart` ignores --env-file, KB #270232)
# and the Starship node_sync DR_HUB_URL self-heal notes live there too.
# Mesh IPs only — MagicDNS dies with the hub. Non-fatal: failover proceeds.
# outpost-us (kytran@, /opt/archie-outpost): watch-product URLs handled in 4d.
DR_MESH=100.64.0.10
FLEET_KEY="$DR/.ssh/id_ed25519"
log "Repointing surviving fleet nodes -> boston-2 ($DR_MESH)..."
fleet_repoint_outposts "$DR_MESH" || log "  (some outposts not repointed — see WARNs above; each self-reports on power-up)"
fleet_kick_starships

# ---- 4b. WTF DB repoint: REMOVED — WTF no longer uses the hub database ----
# This step used to flip WTF_DATABASE_URL from the hub to boston-2. It is obsolete in
# THREE independent ways, each verified live on 2026-09-08:
#   1. WTF's DB is now Citadel-LOCAL: WTF_DATABASE_URL=...@wtf-postgres/wtf, a docker
#      service name inside its own compose stack. There is no hub DB to move.
#   2. WTF_HOST/WTF_DIR pointed at kytran@100.64.0.2:/opt/archie-products/what-the-fact
#      — that path does NOT exist on outpost-us; WTF moved to Citadel in the June migration.
#   3. The sed matched '@100.64.0.4/wtf', which the current URL never contains, so it
#      would have rewritten nothing even had 1 and 2 held.
# Behavioural proof: during the 2026-09-08 hub outage what-the-fact.com served HTTP 200
# throughout. A hub failover does not affect WTF's data path at all.
# Do NOT re-add a repoint here without first checking WTF_DATABASE_URL on the live stack.

# ---- 4c. BEACON front-door: flip ONLY the PLATFORM upstream hub -> boston-2 ----
# The public DNS that points at Beacon must keep reaching the platform (now the
# DR standby) — but Beacon fronts ~20 upstreams and only the platform has a
# boston-2 counterpart (archie_platform_standby, docker-compose.standby.yml).
#
# This used to be a blanket `sed 's|100.64.0.4|100.64.0.10|g'` over the whole
# Caddyfile, which took every hub-only service (KSO, Media Hub, KBS, Plex,
# Jellyfin, Nagios, AdGuard, sandbox, terminal, codex, Tdarr, archie_comms) down
# on EVERY failover — and pre-flipped creed./mesh. before steps 4e/4f had even
# tried to stage their counterparts. Task #5214, ADR-009 (decision #955):
# pointing a hostname at a host that cannot serve it is worse than leaving it
# pointed at one that is merely down.
#
# One :3000 substitution covers platform./api./bridge./consciousness./mediahub.
# because they all `import platform_backend` in Beacon's Caddyfile. That is the
# contract the Caddyfile's own header documents. Non-fatal.
# BEACON_HOST is deliberately NOT set here. beacon_flip.sh owns the front-door
# address AND the BEACON_LOCAL auto-detect (#3245). Re-declaring it here shadowed
# that default with the Beacon VPS IP removed on 2026-08-28, so every DR ingress
# step still dialled a host that does not exist — the helper fix could not reach
# these callers. Override via the ENVIRONMENT if you ever need a different host.
DR_MESH="${DR_MESH:-100.64.0.10}"
BEACON_BAK_SUFFIX=".bak-dr"
log "Repointing Beacon PLATFORM upstream (:$BEACON_DR_PORT_PLATFORM) -> boston-2 ($DR_MESH)..."
beacon_flip_ports "$HUB_MESH" "$DR_MESH" "platform" "$BEACON_DR_PORT_PLATFORM" \
  && log "  Beacon platform aliases now point at the boston-2 standby; hub-only services untouched."

# Assert the selective flip actually stayed selective (#5214 VERIFY). A count of
# 0 means something blanket-flipped Beacon and ~20 healthy services just went
# dark — surface it here rather than letting the owner find it as "KSO is down".
beacon_verify_selective "$HUB_MESH" 10 || \
  tg_notify "DR: Beacon flip was NOT selective — hub-only services may be offline. Run force_reset_to_hub.sh."

# ---- 4c-bis. OUT-OF-SCOPE hostnames -> maintenance splash (ADR-012, #5226) ----
# These have no boston-2 counterpart, so they are deliberately NOT flipped. But
# leaving them aimed at a dead hub only yields an opaque browser error. Serve an
# honest 503 "Services are down or under maintenance" instead. Non-fatal: a failed
# splash must never block a failover — the services are down either way.
beacon_maintenance_mode on "${BEACON_MAINTENANCE_HOSTS[@]}" \
  || log "  WARN: maintenance splash not applied — hub-only hostnames will show a connection error."

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
    # Flip Beacon creed entry hub:8086 -> boston-2:8086. This is now the ONLY
    # thing that moves :8086 — 4c no longer pre-flips it — so creed. and
    # api.creed-ai.org stay pointed at the hub whenever CREED could not be
    # staged here, instead of at a boston-2 with nothing on that port.
    # Gated on CREED actually ANSWERING: `compose up -d` exiting 0 means the
    # container was created, not that it serves. Same rule as mesh. below.
    creed_listening=0
    dr_service_listening "$DR_MESH" "$BEACON_DR_PORT_CREED" "CREED" && creed_listening=1
    if [ "$creed_listening" -eq 1 ]; then
        beacon_flip_ports "$HUB_MESH" "$DR_MESH" "creed" "$BEACON_DR_PORT_CREED"
    else
        log "  CREED is NOT listening on :8086 — LEAVING creed./api.creed-ai.org on the hub (ADR-009)."
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

    # ---- Flip Beacon mesh entry hub:8095 -> boston-2:8095, but ONLY if Headscale
    # is genuinely ANSWERING here. mesh.kytranempowerment.com is the Headscale
    # CONTROL PLANE; moving it to a host that is not serving :8095 severs node
    # enrollment and key rotation at the exact moment mesh health matters most,
    # and it is the failure that dropped both LAN Starships on 2026-07-26.
    # `docker compose up -d` exiting 0 only means the container was CREATED —
    # it is not evidence that anything is listening. Probe before pointing.
    # (Tasks #5214 + #5219.)
    hs_listening=0
    dr_service_listening "$DR_MESH" "$BEACON_DR_PORT_HEADSCALE" "Headscale DR" && hs_listening=1
    if [ "$hs_listening" -eq 1 ]; then
        beacon_flip_ports "$HUB_MESH" "$DR_MESH" "headscale/mesh." "$BEACON_DR_PORT_HEADSCALE"
    else
        log "  Headscale DR is NOT listening on :8095 — LEAVING mesh.kytranempowerment.com on the hub."
        log "  (Pointing the control plane at a host that cannot serve it is worse than leaving it"
        log "   pointed at one that is merely down — ADR-009. The mesh DATA plane is unaffected.)"
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
# NOTE (task #3787): platform.kytranempowerment.com DNS STAYS on the Beacon
# front-door (2.25.170.252) at all times — like every other hub subdomain.
# Failover is handled by step 4c above (flip Beacon's Caddy upstream hub->boston-2),
# so the public DNS that points at Beacon keeps reaching the DR standby. We do NOT
# flip the platform A-record off Beacon: doing so previously stranded platform on
# boston-2 when failback forgot to flip it back. dns_flip.sh is retained ONLY as a
# manual EMERGENCY tool for a Beacon-itself-down scenario (see its header).
log "platform DNS stays on the front door (Citadel 2.25.133.122); failover handled by its upstream flip (4c)."

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
