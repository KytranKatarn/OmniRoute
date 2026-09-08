#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. DR — Phase 7 Quorum Auto-Promote Watchdog (#3685)
# Runs ON boston-2 (the only node that can promote itself) once per cycle via a
# systemd timer (default 60s). Detects a hub outage from MULTIPLE independent
# vantages (quorum) and, after a human-abortable delay, runs failover.sh.
#
#   Owner-locked design (2026-06-02): staged auto-promote · multi-node quorum.
#   Spec: .claude/plans/dr-phase7-quorum-watchdog.md
#
# ONE invocation = ONE cycle. State persists in $DR/watchdog_state between runs.
#
# SAFETY (defense in depth):
#   • boston-2 must ALSO see the hub down (its own vantage) — never acts on
#     outpost reports alone.
#   • Quorum: >= QUORUM of the 3 outposts must independently confirm hub-down.
#     An outpost we cannot SSH does NOT count as a down-vote (guards boston-2's
#     own mesh blip from manufacturing a false quorum).
#   • K consecutive down-cycles before arming (rides out transient blips).
#   • 5-min abort window with Telegram /dr_abort.
#   • failover.sh's own split-brain guard = final backstop.
#   • .watchdog_disabled kill switch (planned-maintenance foot-gun — SET THIS
#     before any intentional hub downtime).
#   • .failed_over one-shot marker — never double-fire; cleared on failback.
#
# DRY_RUN=1 → full cycle (arm, window, abort-poll) but echoes failover.sh
# instead of running it, and does NOT write .failed_over (so you can re-drill).
# ============================================================================
set -uo pipefail

# ---- Config (env-overridable; no hardcoded magic) ----
DR="${DR:-/opt/archie-dr}"
# Exported so the LOCAL probe (`bash probe_hub.sh`, a child process) and the
# REMOTE outpost probes (passed explicitly over SSH below) all target the SAME
# configured hub — HUB_MESH is the single source of truth, not probe_hub's default.
export HUB_MESH="${HUB_MESH:-100.64.0.4}"
DR_MESH="${DR_MESH:-100.64.0.10}"
FLEET_KEY="${FLEET_KEY:-$DR/.ssh/id_ed25519}"
PROBE_SCRIPT="${PROBE_SCRIPT:-$DR/watchdog/probe_hub.sh}"
FAILOVER_SCRIPT="${FAILOVER_SCRIPT:-$DR/failover.sh}"
STATE="${STATE:-$DR/watchdog_state}"
DISABLED_FLAG="${DISABLED_FLAG:-$DR/.watchdog_disabled}"
FAILED_OVER_FLAG="${FAILED_OVER_FLAG:-$DR/.failed_over}"

# Quorum vantages: the 3 surviving global outposts (root@, DR key). Mesh IPs
# only — MagicDNS dies with the hub. Same set failover.sh repoints. Override by
# pre-declaring the OUTPOSTS array (e.g. in a sourced config), else default to 3.
if ! declare -p OUTPOSTS >/dev/null 2>&1; then
  OUTPOSTS=( root@100.64.0.5 root@100.64.0.7 root@100.64.0.8 )
fi
QUORUM="${QUORUM:-2}"            # outpost down-votes required (majority of 3)
K="${K:-3}"                     # consecutive down-cycles before arming (confirmed-down quorum)
K_BLACKOUT="${K_BLACKOUT:-5}"   # cycles before arming when ALL outposts are unreachable
                                # (mesh died with hub — weaker signal, needs more evidence)
ABORT_WINDOW="${ABORT_WINDOW:-300}"   # seconds between arm and fire (5 min)
SSH_TIMEOUT="${SSH_TIMEOUT:-15}"
ARMED_POLL_INTERVAL="${ARMED_POLL_INTERVAL:-5}"   # while armed, read taps this often (s)
SNOOZE_STANDBY_SECONDS="${SNOOZE_STANDBY_SECONDS:-900}"   # ⏸ Standby: hold 15 min, then re-check
SNOOZE_CANCEL_SECONDS="${SNOOZE_CANCEL_SECONDS:-3600}"    # 🛑 Cancel: snooze 1 h, then resume scanning
SNOOZE_FILE="${SNOOZE_FILE:-$DR/.snooze_until}"
# Early close (owner request 2026-07-26): end a snooze as soon as the hub is
# demonstrably back, instead of idling disarmed for the rest of the window.
# K_UP mirrors K — a CONSECUTIVE-healthy streak, so a hub bouncing through a
# deploy cannot be mistaken for a recovery. Set SNOOZE_EARLY_CLOSE=0 to disable.
SNOOZE_EARLY_CLOSE="${SNOOZE_EARLY_CLOSE:-1}"
K_UP="${K_UP:-3}"                                          # consecutive hub-UP cycles to close early
SNOOZE_UP_STREAK="${SNOOZE_UP_STREAK:-$DR/.snooze_up_streak}"
DRY_RUN="${DRY_RUN:-0}"
# Hub liveness heartbeat (cont-102, KB #276817). The hub posts $HEARTBEAT_FILE
# over a PUBLIC, mesh-INDEPENDENT path when its local DB is healthy. A FRESH
# heartbeat during a mesh outage = the hub is ALIVE-but-mesh-isolated, NOT dead
# → auto-failover is SUPPRESSED (promoting would split-brain a live DB).
HEARTBEAT_FILE="${HEARTBEAT_FILE:-$DR/.hub_heartbeat}"
HEARTBEAT_MAX_AGE="${HEARTBEAT_MAX_AGE:-300}"   # seconds; older = stale (hub really gone)

log(){ echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
now_epoch(){ date +%s; }

# Shared Telegram helper (defines tg_notify). Fail-safe stub if absent.
if [ -f "$DR/tg_notify.sh" ]; then
  # shellcheck disable=SC1091
  . "$DR/tg_notify.sh"
else
  log "  (WARN: $DR/tg_notify.sh missing — alerts disabled)"
  tg_notify(){ :; }
fi

# ---- Pure helpers (unit-testable; no I/O) ----
# count_down <result>...  — echoes how many args equal "down".
count_down(){
  local n=0 r
  for r in "$@"; do [ "$r" = "down" ] && n=$((n+1)); done
  echo "$n"
}
# quorum_met <down_count> — exit 0 if down_count >= QUORUM.
quorum_met(){ [ "${1:-0}" -ge "${QUORUM:-2}" ]; }
# count_unreachable <result>... — echoes how many args equal "unreachable".
count_unreachable(){ local n=0 r; for r in "$@"; do [ "$r" = "unreachable" ] && n=$((n+1)); done; echo "$n"; }
# blackout_quorum_met <unreachable_count> <total_outposts>
# True when ALL outposts are unreachable — Headscale (on hub) is down, not a single-node blip.
blackout_quorum_met(){ [ "${1:-0}" -ge "${2:-3}" ] && [ "${2:-3}" -gt 0 ]; }
# hub_heartbeat_fresh — exit 0 if the hub posted a LIVE heartbeat within
# HEARTBEAT_MAX_AGE seconds AND it reported db=ok. The hub writes $HEARTBEAT_FILE
# over a mesh-INDEPENDENT public path, so freshness here = "hub alive but
# mesh-isolated" → suppress failover. Reads the file + clock only (testable by
# overriding HEARTBEAT_FILE / HEARTBEAT_MAX_AGE).
hub_heartbeat_fresh(){
  [ -f "$HEARTBEAT_FILE" ] || return 1
  local line ts db now age
  line="$(cat "$HEARTBEAT_FILE" 2>/dev/null)" || return 1
  ts="$(printf '%s\n' "$line" | sed -n 's/.*ts=\([0-9][0-9]*\).*/\1/p')"
  db="$(printf '%s\n' "$line" | sed -n 's/.*db=\([a-zA-Z][a-zA-Z]*\).*/\1/p')"
  [ -n "$ts" ] && [ "$db" = "ok" ] || return 1
  now="$(now_epoch)"; age=$(( now - ts ))
  [ "$age" -ge 0 ] && [ "$age" -le "${HEARTBEAT_MAX_AGE:-300}" ]
}

# ---- State (key=val, sourced) ----
consec_down=0
armed_at=0
load_state(){
  consec_down=0; armed_at=0
  [ -f "$STATE" ] || return 0
  # shellcheck disable=SC1090
  . "$STATE" 2>/dev/null || true
  consec_down="${consec_down:-0}"; armed_at="${armed_at:-0}"
}
save_state(){ printf 'consec_down=%s\narmed_at=%s\n' "$consec_down" "$armed_at" > "$STATE"; }
reset_state(){ consec_down=0; armed_at=0; save_state; }

# ---- Snooze: time-boxed suppression from the Cancel/Standby buttons. Unlike
# the manual .watchdog_disabled kill switch (indefinite, for planned
# maintenance), a snooze AUTO-EXPIRES back to scanning. ----
set_snooze(){ echo $(( $(now_epoch) + ${1:-0} )) > "$SNOOZE_FILE"; }
# Echoes remaining snooze seconds if still snoozed, else clears the file + echoes nothing.
snooze_remaining(){
  [ -f "$SNOOZE_FILE" ] || return 0
  local until now; until="$(cat "$SNOOZE_FILE" 2>/dev/null || echo 0)"; now="$(now_epoch)"
  if [ "${until:-0}" -gt "$now" ] 2>/dev/null; then echo $(( until - now )); else rm -f "$SNOOZE_FILE"; fi
}

# ---- Probes ----
# boston-2's own vantage. Returns 0 = hub UP, 1 = hub DOWN.
probe_local(){ bash "$PROBE_SCRIPT"; }
# One outpost. Streams the probe over SSH (no pre-deploy needed). Echoes
# up | down | unreachable.
probe_outpost(){
  local node="$1" rc
  if [ ! -f "$FLEET_KEY" ]; then echo "unreachable"; return; fi
  # SSH does NOT forward env — pass the hub config explicitly so every outpost
  # probes the SAME hub the coordinator is configured for ($HUB_MESH is an IP
  # literal, safe to interpolate). The remote `VAR=x bash -s` sets it before the
  # streamed probe runs.
  if ssh -i "$FLEET_KEY" -o ConnectTimeout="$SSH_TIMEOUT" \
        -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
        "$node" "HUB_MESH='$HUB_MESH' PROBE_TCP_TIMEOUT='${PROBE_TCP_TIMEOUT:-5}' PROBE_HTTP_TIMEOUT='${PROBE_HTTP_TIMEOUT:-8}' bash -s" \
        < "$PROBE_SCRIPT" >/dev/null 2>&1; then
    echo "up"        # probe exit 0 = hub reachable from that outpost
  else
    rc=$?
    # exit 1 = probe ran and says hub down; 255 = ssh itself failed.
    if [ "$rc" -eq 255 ]; then echo "unreachable"; else echo "down"; fi
  fi
}

# ---- Telegram action poll (getUpdates; works with the hub's long-poll bot OFF) ----
# Echoes the operator's latest DRP action since $1 (epoch): proceed | abort |
# standby | "" (none). Reads BOTH text commands and inline-button callback_query
# presses from the owner chat, and acks taps via answerCallbackQuery so the
# button spinner clears. Handled ON boston-2 → works during a real hub outage.
#   proceed  : /dr_proceed  · button "dr_proceed"
#   abort    : /dr_abort /dr_cancel abort cancel · button "dr_abort"
#   standby  : /dr_standby standby · button "dr_standby"
# ---------------------------------------------------------------------------
# Is boston-2 GENUINELY a streaming replica of the hub? (#4997)
#
# Asked LOCALLY on boston-2, from live connection state rather than config:
#   * pg_is_in_recovery() = t     -> it is a replica at all. A PROMOTED FORK
#                                    returns f, which is exactly the state that
#                                    went unnoticed for days.
#   * pg_stat_wal_receiver        -> a walreceiver is actually CONNECTED, and to
#     status='streaming', sender     the RIGHT primary.
#     = the hub
#
# Both are observed state. "The script exited 0" is NOT evidence that replication
# exists — assuming it was is what let DR report healthy while boston-2 was a fork.
# Returns 2 (unknown) if it cannot look; an unknown must never read as a pass.
# ---------------------------------------------------------------------------
B2_CONTAINER="${B2_CONTAINER:-archie_dr_replica}"
B2_PG="${B2_PG:-5433}"
HUB_MESH="${HUB_MESH:-100.64.0.4}"

dr_replica_streaming(){
  local out
  out="$(docker exec "$B2_CONTAINER" psql -U archie -p "$B2_PG" -tAc \
        "SELECT pg_is_in_recovery()::text || ':' || coalesce((SELECT status || '@' || coalesce(sender_host,'?') FROM pg_stat_wal_receiver LIMIT 1),'no_receiver');" 2>/dev/null | tr -d '[:space:]')"
  if [ -z "$out" ]; then
    log "  replica check: could not query $B2_CONTAINER — treating as NOT verified"
    return 2
  fi
  case "$out" in
    # NB: pg_is_in_recovery()::text renders "true"/"false", NOT "t"/"f" — verified
    # against the live replica, which returns exactly `true:streaming@100.64.0.4`.
    # Matching t:/f: here would make a genuinely streaming replica report NOT
    # streaming, i.e. a verify that can never pass.
    "true:streaming@$HUB_MESH") log "  replica check: OK — streaming from the hub ($out)"; return 0 ;;
    false:*) log "  replica check: pg_is_in_recovery()=false — boston-2 is a PROMOTED FORK, not a replica ($out)"; return 1 ;;
    *)   log "  replica check: NOT streaming from $HUB_MESH ($out)"; return 1 ;;
  esac
}

# A decision can be given WITHOUT Telegram (#4997 problem 2). Approval used to be
# reachable only via an inline-keyboard callback, so a broken bot — or an operator
# on a terminal, or an agent doing incident response — could not answer at all, and
# DR would sit blocked indefinitely. Worse, per #4995 the logs could not even prove
# the alert had been delivered.
#
#   echo rebuild      > /opt/archie-dr/.dr_decision
#   echo skip_rebuild > /opt/archie-dr/.dr_decision
#   echo verify       > /opt/archie-dr/.dr_decision
#
# Checked BEFORE Telegram, so it works when Telegram is entirely dead — which is
# exactly when you need it. SINGLE-USE: the file is removed as soon as it is read,
# because a decision left on disk would re-fire every cycle and re-run a failback.
poll_action(){
  local since="$1"
  local dfile="$DR/.dr_decision"
  if [ -f "$dfile" ]; then
    local d
    d="$(tr -d '[:space:]' < "$dfile" 2>/dev/null | tr '[:upper:]' '[:lower:]')"
    rm -f "$dfile"
    # NOTE the '>&2' on every log below — it is load-bearing, not style (#5439).
    # poll_action returns its value on STDOUT (`echo "$d"`) and the caller does
    # `action="$(poll_action ...)"`. log() also writes to STDOUT, so an unredirected
    # log here is CAPTURED INTO $action: the caller saw "[ts]   decision 'rebuild'
    # read from ...\nrebuild", which matches no case and fell through to "awaiting
    # decision". And because `rm -f "$dfile"` above already consumed the file, the
    # request was destroyed AND the log line that would have explained it was
    # swallowed into the variable — silent, single-use, unrecoverable.
    # This broke exactly the no-Telegram escape hatch that exists for when the bot
    # is dead. Keep log output OFF stdout in any function whose value is captured.
    case "$d" in
      proceed|abort|standby|rebuild|skip_rebuild|verify) log "  decision '$d' read from $dfile" >&2; echo "$d"; return ;;
      "") : ;;
      *) log "  WARN: ignoring unrecognised decision '$d' in $dfile" >&2 ;;
    esac
  fi
  [ -f "$DR/.telegram_env" ] || { echo ""; return; }
  # shellcheck disable=SC1091
  . "$DR/.telegram_env"
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || { echo ""; return; }
  TG_TOKEN="$TELEGRAM_BOT_TOKEN" TG_CHAT="$TELEGRAM_CHAT_ID" TG_SINCE="$since" python3 - <<'PY' 2>/dev/null
import os, json, urllib.request
tok=os.environ["TG_TOKEN"]; chat=str(os.environ["TG_CHAT"]); since=int(os.environ["TG_SINCE"])
def api(method, **params):
    import urllib.parse
    data=urllib.parse.urlencode(params).encode()
    return urllib.request.urlopen("https://api.telegram.org/bot%s/%s"%(tok,method), data=data, timeout=12).read()
def classify(t):
    t=(t or "").strip().lower().lstrip("/")
    if t in ("dr_proceed","proceed"): return "proceed"
    if t in ("dr_abort","dr_cancel","abort","cancel"): return "abort"
    if t in ("dr_standby","standby"): return "standby"
    if t in ("dr_rebuild","rebuild"): return "rebuild"
    if t in ("dr_skip_rebuild","skip_rebuild","skip"): return "skip_rebuild"
    if t in ("dr_verify","verify"): return "verify"
    return ""
try:
    raw=urllib.request.urlopen("https://api.telegram.org/bot%s/getUpdates?timeout=0"%tok, timeout=12).read()
    upd=json.loads(raw).get("result", [])
except Exception:
    print(""); raise SystemExit
# Priority: an explicit Proceed beats Abort beats Standby within the window.
found={"proceed":False,"abort":False,"standby":False,"rebuild":False,"skip_rebuild":False,"verify":False}
for u in upd:
    cq=u.get("callback_query")
    if cq:
        m=cq.get("message") or {}
        if str((m.get("chat") or {}).get("id"))==chat and int(m.get("date",0))>=since-5:
            a=classify(cq.get("data"))
            if a: found[a]=True
            try: api("answerCallbackQuery", callback_query_id=cq.get("id"), text="DRP: %s"%(a or "noted"))
            except Exception: pass
        continue
    m=u.get("message") or u.get("edited_message") or {}
    if str((m.get("chat") or {}).get("id"))!=chat: continue
    if int(m.get("date",0))<since: continue
    a=classify(m.get("text"))
    if a: found[a]=True
print("proceed" if found["proceed"] else "abort" if found["abort"] else "standby" if found["standby"] else "rebuild" if found["rebuild"] else "skip_rebuild" if found["skip_rebuild"] else "verify" if found["verify"] else "")
PY
}

# Inline keyboard for the arm message (3 buttons across 2 rows).
ARM_KEYBOARD='[[{"text":"✅ Proceed now","callback_data":"dr_proceed"}],[{"text":"🛑 Cancel DRP","callback_data":"dr_abort"},{"text":"⏸ Standby","callback_data":"dr_standby"}]]'

# ---- Fire (real or dry-run) ----
do_failover(){
  # do_failover [force] — pass "force" to run failover.sh --force (human override
  # of its split-brain + heartbeat vetoes; used by /dr_proceed).
  local force_arg=""
  [ "${1:-}" = "force" ] && force_arg="--force"
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN: would run $FAILOVER_SCRIPT ${force_arg:-(no-force)} now (NOT executing; not writing .failed_over)."
    tg_notify $'🧪 <b>DR WATCHDOG DRY-RUN</b>\nQuorum tripped and the abort window elapsed with no /dr_abort. In a REAL run, failover.sh would execute NOW. (Dry-run — hub untouched.)'
    # Disarm so the drill can be repeated cleanly.
    reset_state
    return 0
  fi
  log "FIRING: quorum confirmed + abort window elapsed → running $FAILOVER_SCRIPT $force_arg"
  touch "$FAILED_OVER_FLAG"               # one-shot BEFORE running (never double-fire)
  bash "$FAILOVER_SCRIPT" $force_arg      # sends its own alerts + split-brain + freshness + heartbeat guards
}

# ---- Main cycle (steps 1–7) ----
# ── OBSERVATION LANE ────────────────────────────────────────────────────────
# 🔴 THIS RUNS BEFORE EVERY PROMOTION GATE, AND THAT IS THE ENTIRE POINT.
#
# On 2026-09-08 the hub was down 20:08-20:22 UTC. This watchdog ran ~14 cycles
# straight through it and logged exactly one line each time:
#     "awaiting decision (rebuild/skip_rebuild/verify) — exit."
# It probed nothing and told nobody. `systemctl is-active dr-watchdog.timer` said
# `active` the whole time. The owner found the outage by opening a browser.
#
# CAUSE: .failed_over / .awaiting_rebuild are PROMOTION gates, but they sat ABOVE
# the probe in main(), so disarming DR also disarmed MONITORING. Those are two
# different questions and must never share a gate:
#     "may I promote boston-2?"  -> correctly gated, and STAYS gated.
#     "is the hub up?"           -> always worth answering, and NEVER gated.
# A degraded-DR posture is when you are MOST exposed, so it must alert MORE, not
# go silent. That is the whole failure this lane exists to prevent.
#
# .watchdog_disabled is the ONE exception: it is an explicit human "be quiet, I am
# doing maintenance", so it suppresses alerts too — but it SAYS SO in the log,
# because unannounced silence is precisely the bug being fixed here.
#
# SAFE BY CONSTRUCTION: this observes only. It never promotes, never runs
# failover.sh, never writes a DR flag, and never returns non-zero — its caller
# invokes it with `|| true` so a broken probe can never take the watchdog down
# with it.
observe_and_alert(){
  local sf="$DR/.hub_observed_state" kf="$DR/.hub_observed_streak" df="$DR/.hub_down_since"
  local confirm="${OBSERVE_CONFIRM:-2}" obs last streak now mins down_since

  if [ -f "$DISABLED_FLAG" ]; then
    log "observation: alerts SUPPRESSED by $DISABLED_FLAG (planned maintenance)."
    return 0
  fi

  if probe_local >/dev/null 2>&1; then obs=up; else obs=down; fi
  last="$(cat "$sf" 2>/dev/null || echo '')"
  now="$(now_epoch)"

  # Steady state — nothing to say. Clearing the streak here is what makes a
  # single flapping cycle unable to accumulate into a false report.
  if [ "$obs" = "$last" ]; then rm -f "$kf"; return 0; fi

  # First ever run: adopt the current state silently rather than paging about a
  # transition nobody observed the start of.
  if [ -z "$last" ]; then
    echo "$obs" > "$sf"
    [ "$obs" = "down" ] && echo "$now" > "$df"
    log "observation: baseline recorded as $obs (no alert on first observation)."
    return 0
  fi

  streak=$(( $(cat "$kf" 2>/dev/null || echo 0) + 1 ))
  echo "$streak" > "$kf"
  if [ "$streak" -lt "$confirm" ]; then
    log "observation: hub looks $obs (${streak}/${confirm} confirmations) — holding."
    return 0
  fi

  rm -f "$kf"
  echo "$obs" > "$sf"

  if [ "$obs" = "down" ]; then
    echo "$now" > "$df"
    log "observation: hub DOWN confirmed over ${confirm} consecutive checks — alerting."
    tg_notify "🔴 <b>Starbase (hub) is DOWN</b> — confirmed from Citadel over ${confirm} consecutive checks.

Products on Citadel are unaffected. <code>platform.kytranempowerment.com</code> and product sign-in will return 502 until it is back.

<i>Observation only — no failover has been triggered.</i>"
  else
    mins=""
    if [ -f "$df" ]; then
      down_since="$(cat "$df" 2>/dev/null || echo "$now")"
      mins=" after $(( (now - down_since) / 60 )) min down"
      rm -f "$df"
    fi
    log "observation: hub RECOVERED${mins} — alerting."
    tg_notify "✅ <b>Starbase (hub) is back</b>${mins} — reachable from Citadel again."
  fi
  return 0
}

main(){
  # 0. OBSERVE + ALERT. Deliberately ABOVE every gate below — see the comment on
  #    observe_and_alert. `|| true` so observation can never break promotion logic.
  observe_and_alert || true
  # 1. Disarm / planned-maintenance kill switch.
  if [ -f "$DISABLED_FLAG" ]; then log "disabled ($DISABLED_FLAG present) — exit."; exit 0; fi
  # 2. Post-failover recovery: hub came back — auto-repoint then request approval for DB rebuild.
  AWAITING_REBUILD="$DR/.awaiting_rebuild"
  if [ -f "$FAILED_OVER_FLAG" ]; then
    if [ ! -f "$AWAITING_REBUILD" ] && probe_local; then
      # Hub just recovered — run Phase 1 auto-repoint + send Telegram approval request
      log "Hub recovered after DR failover — running Phase 1 auto-repoint..."
      bash "$DR/auto_failback.sh"        # sends its own Telegram msg at the end
      echo "$(now_epoch)" > "$AWAITING_REBUILD"
      exit 0
    elif [ -f "$AWAITING_REBUILD" ]; then
      # Phase 1 done — poll for operator's DB rebuild decision (one check per cycle)
      since="$(cat "$AWAITING_REBUILD" 2>/dev/null || echo 0)"
      action="$(poll_action "$since")"
      case "$action" in
        rebuild)
          # failback.sh restore-normal is SAFE: it never touches the hub DB. The
          # wipe lives ONLY in `rebuild-hub`, which is CONFIRM=REBUILD-HUB gated.
          # (KB #272172's blanket "DO NOT run failback.sh" is over-broad and names
          # the wrong thing — `rebuild-hub` is the dangerous subcommand.)
          #
          # BUT restore-normal's step 5 only PRINTS "ON BOSTON-2: setup_replica.sh".
          # The old code ran it, deleted BOTH flags, and announced "boston-2 is a
          # streaming replica" while nothing had re-cloned anything — which is how
          # boston-2 became a promoted fork with DR believed healthy and the
          # evidence erased.
          log "Operator approved DB rebuild — restore-normal, then re-establish the replica..."
          tg_notify "🔄 <b>DR Failback — restoring services, then rebuilding the replica...</b>"
          bash "$DR/failback.sh" restore-normal 2>&1 | tee -a "$DR/failback.log"
          log "running setup_replica.sh (restore-normal only PRINTS this step)..."
          bash "$DR/setup_replica.sh" 2>&1 | tee -a "$DR/failback.log"
          if dr_replica_streaming; then
            rm -f "$AWAITING_REBUILD" "$FAILED_OVER_FLAG"
            tg_notify "✅ <b>DR Failback complete.</b> VERIFIED: boston-2 is streaming from the hub. Normal DR posture restored."
          else
            log "replica NOT verified — keeping .awaiting_rebuild/.failed_over."
            tg_notify "🔴 <b>DR Failback INCOMPLETE.</b> Services are back on the hub, but boston-2 is <b>NOT streaming</b> — DR is NOT protected. Flags kept so this stays visible. Fix replication, then answer <code>verify</code>."
          fi ;;
        skip_rebuild)
          # Deliberately no longer clears .failed_over: skipping leaves DR truly
          # degraded, and erasing the evidence made that indistinguishable from a
          # healthy system.
          log "Operator skipped DB rebuild — DR remains degraded (.failed_over kept)."
          rm -f "$AWAITING_REBUILD"
          tg_notify "🔵 <b>DB rebuild skipped.</b> boston-2 is a cold standby and <b>DR is NOT protected</b>. .failed_over is kept so the degraded state stays visible. Run <code>setup_replica.sh</code> on boston-2, then answer <code>verify</code>." ;;
        verify)
          # The third state the old code could not express: "already rebuilt
          # out-of-band". Clears flags ONLY on proof of live streaming.
          log "Operator requested verify — checking real replication state..."
          if dr_replica_streaming; then
            rm -f "$AWAITING_REBUILD" "$FAILED_OVER_FLAG"
            tg_notify "✅ <b>DR verified.</b> boston-2 is streaming from the hub. Flags cleared; normal DR posture restored."
          else
            tg_notify "🔴 <b>Verify FAILED.</b> boston-2 is not streaming from the hub — flags kept. DR is NOT protected."
          fi ;;
        *) log "awaiting decision (rebuild/skip_rebuild/verify) — exit." ;;
      esac
      exit 0
    fi
    log "in DR mode, hub still down — exit."
    exit 0
  fi

  # 2.5 Snoozed by a Cancel/Standby button, or by a planned maintenance window?
  #     Stay silent until it auto-expires — OR until the hub is demonstrably back.
  #
  # EARLY CLOSE (owner request 2026-07-26). A snooze must be sized for the WORST
  # case (a 90-minute PSU/GPU job), which leaves DR disarmed for the full 90 even
  # when the hub came back in 20. Every unused minute is a minute with no cover.
  # So once the hub is confirmed healthy for K_UP CONSECUTIVE cycles, drop the
  # snooze and resume scanning immediately.
  #
  # Deliberately a STREAK, mirroring the confirmed-down quorum (K): a hub that
  # bounces mid-maintenance — deploys restart it repeatedly — must NOT read as
  # recovered. One healthy probe is a blip; K_UP in a row is a trend.
  #
  # SAFE BY CONSTRUCTION: clearing a snooze resumes SCANNING, it does not fail
  # over. If the hub really is healthy, step 3 immediately logs "all clear" and
  # resets. The only thing early close spends is the remaining silence.
  #
  # NOT applied to .watchdog_disabled — that exits at step 1 above. An indefinite
  # kill switch is a human decision and only a human retracts it.
  rem="$(snooze_remaining)"
  if [ -n "${rem:-}" ]; then
    if [ "${SNOOZE_EARLY_CLOSE:-1}" = "1" ] && probe_local; then
      _up=$(( $(cat "$SNOOZE_UP_STREAK" 2>/dev/null || echo 0) + 1 ))
      echo "$_up" > "$SNOOZE_UP_STREAK"
      if [ "$_up" -ge "${K_UP:-3}" ]; then
        rm -f "$SNOOZE_FILE" "$SNOOZE_UP_STREAK"
        log "snooze CLOSED EARLY — hub healthy ${_up}/${K_UP:-3} consecutive cycles (${rem}s were left). Resuming scanning."
        tg_notify "✅ <b>Maintenance snooze ended early</b> — Starbase back and healthy for ${_up} consecutive checks. DR watchdog is scanning again; ${rem}s of the window went unused."
      else
        log "snoozed — ${rem}s left; hub UP ${_up}/${K_UP:-3} consecutive (early close at ${K_UP:-3})."
        exit 0
      fi
    else
      # Hub still down, or early close switched off — a blip must not accumulate.
      rm -f "$SNOOZE_UP_STREAK"
      log "snoozed — ${rem}s until scanning resumes."
      exit 0
    fi
  fi

  load_state

  # 3. boston-2's own vantage. Hub reachable → all clear, reset, exit.
  #    This is also where a recovery is caught: if we were armed and the hub
  #    comes back, stand down and tell the owner.
  if probe_local; then
    if [ "$armed_at" -ne 0 ]; then
      log "Starbase reachable from boston-2 → was ARMED, standing down."
      tg_notify $'✅ <b>DR WATCHDOG — Starbase recovered</b>\nThe Starbase is reachable again. Auto-failover CANCELLED. Still on warm standby.'
    elif [ "$consec_down" -ne 0 ]; then
      log "Starbase reachable from boston-2 → clearing down-counter."
    fi
    reset_state
    exit 0
  fi
  log "hub DOWN from boston-2 vantage — polling outpost quorum..."

  # 4. Outpost vantages.
  results=()
  for node in "${OUTPOSTS[@]}"; do
    r="$(probe_outpost "$node")"
    log "  $node: $r"
    results+=( "$r" )
  done
  down_count="$(count_down "${results[@]}")"
  unreachable_count="$(count_unreachable "${results[@]}")"

  # 5. Quorum test — two valid failure modes:
  #   a) Normal:   >= QUORUM outposts confirm hub-down  → arm at K cycles
  #   b) Blackout: ALL outposts unreachable             → arm at K_BLACKOUT cycles
  #      Outposts go unreachable when Headscale (on hub) dies — they lose the
  #      control plane and can't SSH-probe. This is evidence the hub is down,
  #      not just a boston-2 blip.  The higher K_BLACKOUT threshold guards against
  #      a transient fleet-wide connectivity event.
  _blackout=0
  if quorum_met "$down_count"; then
    : # standard confirmed-down quorum — unchanged path
  elif blackout_quorum_met "$unreachable_count" "${#OUTPOSTS[@]}"; then
    log "BLACKOUT: all ${#OUTPOSTS[@]} outposts unreachable (Headscale/mesh likely down with hub). Using K_BLACKOUT=$K_BLACKOUT."
    _blackout=1
  else
    log "no quorum ($down_count/${#OUTPOSTS[@]} down, $unreachable_count unreachable; need $QUORUM confirmed OR all-unreachable) → transient blip. Reset."
    reset_state
    exit 0
  fi
  consec_down=$((consec_down+1))
  save_state
  _arm_at=$K; [ "$_blackout" -eq 1 ] && _arm_at=$K_BLACKOUT
  log "$([ "$_blackout" -eq 1 ] && echo "BLACKOUT" || echo "QUORUM") Starbase-down ($down_count down, $unreachable_count unreachable). consecutive=$consec_down (arm at $_arm_at)."

  # 6. Arm — alert the owner with tappable Proceed / Cancel / Standby buttons.
  if [ "$consec_down" -ge "$_arm_at" ] && [ "$armed_at" -eq 0 ]; then
    armed_at="$(now_epoch)"; save_state
    _hb_state="dead/unknown"; hub_heartbeat_fresh && _hb_state="ALIVE (mesh-isolated)"
    log "ARMED at $armed_at (mode: $([ "$_blackout" -eq 1 ] && echo BLACKOUT || echo QUORUM); hub heartbeat: $_hb_state). Auto-failover in ${ABORT_WINDOW}s unless cancelled."
    if hub_heartbeat_fresh; then
      # cont-102: hub unreachable over the mesh but POSTING a live heartbeat over
      # the public path (DB healthy) → mesh-isolation, NOT death. Still alert (the
      # owner must know the hub fell off the mesh), but the window-expiry fire is
      # VETOED below — this message sets that expectation.
      tg_notify "🛰️ <b>A.R.C.H.I.E. DR — HUB UNREACHABLE OVER MESH (but ALIVE)</b>
boston-2 + outposts cannot reach the hub over the mesh ($HUB_MESH), BUT the hub is posting a LIVE heartbeat over the public path (DB healthy). This looks like a MESH ISOLATION, not a hub death.
<b>I will NOT auto-promote</b> (that would split-brain a live DB). Fix the mesh — or reply <code>/dr_proceed</code> to FORCE failover if you are certain the hub DB is dead.
🛑 Cancel (snooze $((SNOOZE_CANCEL_SECONDS/60)) min) · ⏸ Standby (hold $((SNOOZE_STANDBY_SECONDS/60)) min)." "$ARM_KEYBOARD"
    elif [ "$_blackout" -eq 1 ]; then
      tg_notify "⚠️ <b>A.R.C.H.I.E. DR WATCHDOG — HUB DOWN (BLACKOUT)</b>
boston-2 cannot reach the hub ($HUB_MESH) AND all ${#OUTPOSTS[@]} outposts are unreachable — Headscale/mesh died with the hub.
<b>Auto-failover to boston-2 in $((ABORT_WINDOW/60)) min.</b>
✅ Proceed now (fail over) · 🛑 Cancel (snooze $((SNOOZE_CANCEL_SECONDS/60)) min) · ⏸ Standby (hold $((SNOOZE_STANDBY_SECONDS/60)) min).
Or reply <code>/dr_proceed</code> · <code>/dr_abort</code> · <code>/dr_standby</code>." "$ARM_KEYBOARD"
    else
      tg_notify "⚠️ <b>A.R.C.H.I.E. DR WATCHDOG — HUB DOWN (quorum)</b>
boston-2 + $down_count/${#OUTPOSTS[@]} outposts cannot reach the hub ($HUB_MESH).
<b>Auto-failover to boston-2 in $((ABORT_WINDOW/60)) min.</b>
✅ Proceed now (fail over) · 🛑 Cancel (snooze $((SNOOZE_CANCEL_SECONDS/60)) min) · ⏸ Standby (hold $((SNOOZE_STANDBY_SECONDS/60)) min).
Or reply <code>/dr_proceed</code> · <code>/dr_abort</code> · <code>/dr_standby</code>." "$ARM_KEYBOARD"
    fi
  fi

  # 7. ARMED → responsive action loop. Polls Telegram every ARMED_POLL_INTERVAL
  #    seconds so a tap is acknowledged within seconds, re-checks hub recovery
  #    periodically, and fires when the abort window elapses with no response.
  #    Runs the rest of the window in THIS invocation (systemd serialises the
  #    oneshot, so the timer won't double-fire; TimeoutStartSec covers it). A
  #    crash/reboot mid-window simply re-enters here using the saved armed_at.
  if [ "$armed_at" -ne 0 ]; then
    _i=0
    while :; do
      [ -f "$DISABLED_FLAG" ]    && { log "disabled mid-window — exit."; exit 0; }
      [ -f "$FAILED_OVER_FLAG" ] && { log "already failed over — exit."; exit 0; }
      case "$(poll_action "$armed_at")" in
        proceed)
          log "operator PROCEED — firing now (force: overrides split-brain + heartbeat veto)."
          tg_notify $'⏩ <b>DR WATCHDOG — PROCEED received</b>\nFailing over to boston-2 NOW (forced).'
          do_failover force; exit 0 ;;
        abort)
          set_snooze "$SNOOZE_CANCEL_SECONDS"; reset_state
          log "operator CANCEL — snoozing ${SNOOZE_CANCEL_SECONDS}s, then resume scanning."
          tg_notify "🛑 <b>DR WATCHDOG — CANCELLED</b>
This alert is cancelled. I will stay silent for <b>$((SNOOZE_CANCEL_SECONDS/60)) min</b>, then resume scanning — if the hub is still down I'll alert again. (NOT disabled permanently.)"
          exit 0 ;;
        standby)
          set_snooze "$SNOOZE_STANDBY_SECONDS"; reset_state
          log "operator STANDBY — snoozing ${SNOOZE_STANDBY_SECONDS}s, then re-check."
          tg_notify "⏸ <b>DR WATCHDOG — STANDBY</b>
Holding for <b>$((SNOOZE_STANDBY_SECONDS/60)) min</b>, then I'll re-check and alert again if the hub is still down."
          exit 0 ;;
      esac
      now="$(now_epoch)"
      # Fire when the abort window elapses (re-confirm hub still down first).
      if [ "$now" -gt $((armed_at + ABORT_WINDOW)) ]; then
        if probe_local; then
          log "Starbase recovered at window expiry — standing down."
          tg_notify $'✅ <b>DR WATCHDOG — Starbase recovered</b>\nThe Starbase is reachable again. Auto-failover CANCELLED. Still on warm standby.'
          reset_state; exit 0
        fi
        # cont-102 heartbeat VETO: the hub may be mesh-isolated but ALIVE. A fresh,
        # DB-healthy heartbeat over the public path means promoting now would
        # split-brain a live DB → SUPPRESS the auto-fire (human can still /dr_proceed).
        if hub_heartbeat_fresh; then
          log "window elapsed BUT hub heartbeat FRESH (DB healthy) — mesh-isolation, NOT death. SUPPRESSING auto-failover; snoozing ${SNOOZE_STANDBY_SECONDS}s."
          tg_notify "🛰️ <b>DR WATCHDOG — auto-failover SUPPRESSED</b>
The hub is still unreachable over the mesh but is posting a LIVE heartbeat (DB healthy) — mesh-isolation, not death. I am NOT promoting the replica. Holding $((SNOOZE_STANDBY_SECONDS/60)) min then re-checking. Reply <code>/dr_proceed</code> to force failover if you are certain the hub DB is dead."
          set_snooze "$SNOOZE_STANDBY_SECONDS"; reset_state; exit 0
        fi
        log "abort window elapsed, hub still down + no fresh heartbeat — firing."
        do_failover; exit 0
      fi
      # Periodic hub-recovery check (~every 30s; the probe is slow when down).
      _i=$((_i+1))
      if [ $((_i % 6)) -eq 0 ] && probe_local; then
        log "Starbase recovered mid-window — standing down."
        tg_notify $'✅ <b>DR WATCHDOG — Starbase recovered</b>\nThe Starbase is reachable again. Auto-failover CANCELLED. Still on warm standby.'
        reset_state; exit 0
      fi
      sleep "$ARMED_POLL_INTERVAL"
    done
  fi

  exit 0
}

# Library guard — `DR_WATCHDOG_LIB=1 source dr_watchdog.sh` exposes the pure
# helpers (count_down/quorum_met) to the unit test without running main.
[ "${DR_WATCHDOG_LIB:-0}" = "1" ] || main "$@"
