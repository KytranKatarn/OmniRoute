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
K="${K:-3}"                     # consecutive down-cycles before arming
ABORT_WINDOW="${ABORT_WINDOW:-300}"   # seconds between arm and fire (5 min)
SSH_TIMEOUT="${SSH_TIMEOUT:-15}"
ARMED_POLL_INTERVAL="${ARMED_POLL_INTERVAL:-5}"   # while armed, read taps this often (s)
SNOOZE_STANDBY_SECONDS="${SNOOZE_STANDBY_SECONDS:-900}"   # ⏸ Standby: hold 15 min, then re-check
SNOOZE_CANCEL_SECONDS="${SNOOZE_CANCEL_SECONDS:-3600}"    # 🛑 Cancel: snooze 1 h, then resume scanning
SNOOZE_FILE="${SNOOZE_FILE:-$DR/.snooze_until}"
DRY_RUN="${DRY_RUN:-0}"

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
poll_action(){
  local since="$1"
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
    return ""
try:
    raw=urllib.request.urlopen("https://api.telegram.org/bot%s/getUpdates?timeout=0"%tok, timeout=12).read()
    upd=json.loads(raw).get("result", [])
except Exception:
    print(""); raise SystemExit
# Priority: an explicit Proceed beats Abort beats Standby within the window.
found={"proceed":False,"abort":False,"standby":False}
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
print("proceed" if found["proceed"] else "abort" if found["abort"] else "standby" if found["standby"] else "")
PY
}

# Inline keyboard for the arm message (3 buttons across 2 rows).
ARM_KEYBOARD='[[{"text":"✅ Proceed now","callback_data":"dr_proceed"}],[{"text":"🛑 Cancel DRP","callback_data":"dr_abort"},{"text":"⏸ Standby","callback_data":"dr_standby"}]]'

# ---- Fire (real or dry-run) ----
do_failover(){
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN: would run $FAILOVER_SCRIPT now (NOT executing; not writing .failed_over)."
    tg_notify $'🧪 <b>DR WATCHDOG DRY-RUN</b>\nQuorum tripped and the abort window elapsed with no /dr_abort. In a REAL run, failover.sh would execute NOW. (Dry-run — hub untouched.)'
    # Disarm so the drill can be repeated cleanly.
    reset_state
    return 0
  fi
  log "FIRING: quorum confirmed + abort window elapsed → running $FAILOVER_SCRIPT"
  touch "$FAILED_OVER_FLAG"          # one-shot BEFORE running (never double-fire)
  bash "$FAILOVER_SCRIPT"            # sends its own start/complete/partial alerts + split-brain guard
}

# ---- Main cycle (steps 1–7) ----
main(){
  # 1. Disarm / planned-maintenance kill switch.
  if [ -f "$DISABLED_FLAG" ]; then log "disabled ($DISABLED_FLAG present) — exit."; exit 0; fi
  # 2. One-shot — already failed over.
  if [ -f "$FAILED_OVER_FLAG" ]; then log "already failed over ($FAILED_OVER_FLAG) — exit."; exit 0; fi

  # 2.5 Snoozed by a Cancel/Standby button? Stay silent until it auto-expires.
  rem="$(snooze_remaining)"
  if [ -n "${rem:-}" ]; then log "snoozed — ${rem}s until scanning resumes."; exit 0; fi

  load_state

  # 3. boston-2's own vantage. Hub reachable → all clear, reset, exit.
  #    This is also where a recovery is caught: if we were armed and the hub
  #    comes back, stand down and tell the owner.
  if probe_local; then
    if [ "$armed_at" -ne 0 ]; then
      log "hub reachable from boston-2 → was ARMED, standing down."
      tg_notify $'✅ <b>DR WATCHDOG — hub recovered</b>\nThe hub is reachable again. Auto-failover CANCELLED. Still on warm standby.'
    elif [ "$consec_down" -ne 0 ]; then
      log "hub reachable from boston-2 → clearing down-counter."
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

  # 5. Quorum test.
  if ! quorum_met "$down_count"; then
    log "no quorum ($down_count/${#OUTPOSTS[@]} outposts down; need $QUORUM) → likely a boston-2 mesh blip. Reset."
    reset_state
    exit 0
  fi
  consec_down=$((consec_down+1))
  save_state
  log "QUORUM hub-down ($down_count/${#OUTPOSTS[@]}). consecutive=$consec_down (arm at K=$K)."

  # 6. Arm — alert the owner with tappable Proceed / Cancel / Standby buttons.
  if [ "$consec_down" -ge "$K" ] && [ "$armed_at" -eq 0 ]; then
    armed_at="$(now_epoch)"; save_state
    log "ARMED at $armed_at. Auto-failover in ${ABORT_WINDOW}s unless cancelled."
    tg_notify "⚠️ <b>A.R.C.H.I.E. DR WATCHDOG — HUB DOWN (quorum)</b>
boston-2 + $down_count/${#OUTPOSTS[@]} outposts cannot reach the hub ($HUB_MESH).
<b>Auto-failover to boston-2 in $((ABORT_WINDOW/60)) min.</b>
✅ Proceed now (fail over) · 🛑 Cancel (snooze $((SNOOZE_CANCEL_SECONDS/60)) min) · ⏸ Standby (hold $((SNOOZE_STANDBY_SECONDS/60)) min).
Or reply <code>/dr_proceed</code> · <code>/dr_abort</code> · <code>/dr_standby</code>." "$ARM_KEYBOARD"
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
          log "operator PROCEED — firing now."
          tg_notify $'⏩ <b>DR WATCHDOG — PROCEED received</b>\nFailing over to boston-2 NOW.'
          do_failover; exit 0 ;;
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
          log "hub recovered at window expiry — standing down."
          tg_notify $'✅ <b>DR WATCHDOG — hub recovered</b>\nThe hub is reachable again. Auto-failover CANCELLED. Still on warm standby.'
          reset_state; exit 0
        fi
        log "abort window elapsed, hub still down — firing."
        do_failover; exit 0
      fi
      # Periodic hub-recovery check (~every 30s; the probe is slow when down).
      _i=$((_i+1))
      if [ $((_i % 6)) -eq 0 ] && probe_local; then
        log "hub recovered mid-window — standing down."
        tg_notify $'✅ <b>DR WATCHDOG — hub recovered</b>\nThe hub is reachable again. Auto-failover CANCELLED. Still on warm standby.'
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
