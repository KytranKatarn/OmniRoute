#!/bin/bash
# ============================================================================
# adguard_flip.sh — restore the LAN split-horizon after a DRP (task #5224)
#
# WHY THIS EXISTS
# After the 2026-07-25 DRP, 19 of 20 AdGuard rewrites were still pointed at
# 192.168.1.200 (the recovery hub Caddy, `auto_https off`, :443 REFUSED) ~13 hours
# after Beacon, the watch products and the hub had all been correctly reverted.
# Owner-visible symptom: platform./creed./server./media. unreachable over HTTPS
# from the LAN while every service was healthy and public DNS was correct.
#
# THE GAP: no DR script — failover, failback, auto_failback or force_reset_to_hub
# — could read or write AdGuard. force_reset_to_hub.sh advertises "Emergency
# idempotent restore to normal hub state" but structurally COULD NOT restore LAN
# DNS, so a full break-glass reset still left the owner locked out over HTTPS.
#
# ── THE RULE THAT SHAPES EVERYTHING HERE ────────────────────────────────────
# PER-HOST, NEVER BLANKET. A bulk repoint is exactly what caused #5219: sweeping
# all 15 rewrites to 192.168.1.200 swallowed `mesh.`, the TLS-only Headscale
# control plane, and dropped BOTH LAN Starships off the mesh. A batch over N
# hostnames is N decisions (feedback_bulk-ops-are-n-decisions).
#
# Three defences, in order:
#   1. TARGET map — every hostname has ONE declared correct answer. A name not in
#      the map is REPORTED and never written. mail. is Citadel, not Beacon.
#   2. PROTECTED  — mesh. is never written by this script under any flag.
#   3. TLS PROBE  — refuse to point a name at a host with no :443 listener. This
#      is the ADR-009 rule and the direct lesson of #5219; it mirrors
#      adguard_service.PROTECTED_REWRITES' probe in the platform.
#
# DETECT BY DEFAULT. Nothing is written without --apply. A recovery script that
# silently rewrites DNS is how #5219 happened.
#
#   adguard_flip.sh                # report drift, exit 1 if any (SAFE)
#   adguard_flip.sh --serves       # per-host: resolves AND serves TLS? (SAFE)
#   adguard_flip.sh --apply        # repoint drifted hosts, one at a time
#
# AdGuard API is http://127.0.0.1:5354 on the HUB (AdGuardHome `http.address`) —
# NOT 6060, which is pprof and disabled. Because the DR scripts run on boston-2,
# every call is made over SSH to the hub.
# ============================================================================
set -uo pipefail

DR="${DR:-/opt/archie-dr}"
FLEET_KEY="${FLEET_KEY:-$DR/.fleet_key}"
HUB_MESH="${HUB_MESH:-100.64.0.4}"
HUB_SSH="${HUB_SSH:-kytran@$HUB_MESH}"
# The DNS answer these hostnames are EXPECTED to resolve to. Citadel inherited the
# front door when the Beacon VPS was removed 2026-08-28.
BEACON_PUBLIC="${BEACON_PUBLIC:-2.25.133.122}"
CITADEL_PUBLIC="${CITADEL_PUBLIC:-2.25.133.122}"

_ag_log(){ echo "[$(date -u +%H:%M:%S)] [adguard] $*"; }

# Hostnames Beacon fronts. Derived from the live Caddyfile set (2026-07-26).
ADGUARD_BEACON_HOSTS="${ADGUARD_BEACON_HOSTS:-platform consciousness business server media creed adguard nagios plex jellyfin store shop terminal codex sandbox archie claude tdarr}"
# DELIBERATELY EMPTY — and this is the most important line in the file.
#
# My first draft mapped mail. -> Citadel. Running the detect against live AdGuard
# immediately flagged mail. -> 192.168.1.200 as "drift", which would have made
# --apply repoint it to Citadel and break mail.
#
# That is the SAME mistake I made and corrected on 2026-07-26 (KB #284817): a
# per-host grep matched `mx: mail.kytranempowerment.com` inside Citadel's MTA-STS
# POLICY TEXT and I read it as a vhost. Stalwart actually runs on the HUB —
# :25/:465/:587/:993 are open there and closed on Citadel — so mail. belongs on
# 192.168.1.200, which is where it sits today after that correction.
#
# The sources genuinely disagree (operational-state.md and #5224's own description
# both say Citadel fronts mail.), so mail. stays OUT of the map. An unmapped name
# is REPORTED and never written — which is precisely the behaviour a name I am not
# certain about should get. Encoding a guess here would automate an outage.
ADGUARD_CITADEL_HOSTS="${ADGUARD_CITADEL_HOSTS:-}"
# NEVER written here. mesh. is the TLS-only Headscale control plane: clients are
# handed back headscale's configured server_url and must reach it on 443.
ADGUARD_PROTECTED="${ADGUARD_PROTECTED:-mesh.kytranempowerment.com}"

_ag_ssh(){ ssh -i "$FLEET_KEY" -o BatchMode=yes -o ConnectTimeout=15 \
             -o StrictHostKeyChecking=accept-new "$HUB_SSH" "$@" 2>/dev/null; }

# Does <ip> actually terminate TLS on 443? Asked from the HUB, which is where the
# LAN clients resolve to and therefore the vantage that matters.
_ag_tls_ok(){
  local ip="$1" out
  out="$(_ag_ssh "timeout 6 bash -c 'echo > /dev/tcp/${ip}/443' 2>/dev/null && echo TLS_OK || echo TLS_NO")"
  case "$out" in *TLS_OK*) return 0 ;; *TLS_NO*) return 1 ;; *) return 2 ;; esac
}

# Emits "<domain> <current_answer>" per rewrite, via the hub's AdGuard API.
# AUTH: Basic, from ADGUARD_USER/ADGUARD_PASS in the hub's /mnt/archie_brain/.env
# (the API returns 401 unauthenticated — verified live, and my first draft omitted
# the header entirely, which would have made every check return "unknown" forever).
_ag_api(){
  # $1 = python body appended to the preamble; runs ON THE HUB.
  _ag_ssh "python3 - <<'PYX'
import json,urllib.request,base64,re
API='http://127.0.0.1:5354'
u=pw=''
try:
    for line in open('/mnt/archie_brain/.env'):
        m=re.match(r'^(ADGUARD_[A-Z_]+)=(.*)\$', line.strip())
        if m:
            v=m.group(2).strip().strip('\"').strip(\"'\")
            if m.group(1)=='ADGUARD_USER': u=v
            elif m.group(1)=='ADGUARD_PASS': pw=v
except Exception as e:
    print('ERR envread',e); raise SystemExit
AUTH='Basic '+base64.b64encode((u+':'+pw).encode()).decode()
def call(path,payload=None):
    req=urllib.request.Request(API+path); req.add_header('Authorization',AUTH)
    data=None
    if payload is not None:
        data=json.dumps(payload).encode(); req.add_header('Content-Type','application/json')
    with urllib.request.urlopen(req,data=data,timeout=15) as r:
        b=r.read()
        return json.loads(b) if b.strip().startswith((b'[',b'{')) else b[:200]
$1
PYX"
}

_ag_list(){
  _ag_api "
try:
    for it in call('/control/rewrite/list'):
        print(it.get('domain',''), it.get('answer',''))
except Exception as e:
    print('ERR', type(e).__name__, e)
"
}

# Report drift. Exit 0 = clean, 1 = drift found, 2 = could not measure.
adguard_lan_check(){
  local raw drift=0 measured=0
  raw="$(_ag_list)"
  if [ -z "$raw" ] || echo "$raw" | grep -q '^ERR'; then
    _ag_log "could not read AdGuard rewrites (${raw:-no output}) — NOT reporting clean"
    return 2
  fi
  while read -r dom ans; do
    [ -n "$dom" ] || continue
    measured=$((measured+1))
    case " $ADGUARD_PROTECTED " in *" $dom "*) _ag_log "  $dom -> $ans (PROTECTED, never touched)"; continue ;; esac
    local want=""
    for h in $ADGUARD_BEACON_HOSTS;  do [ "$dom" = "$h.kytranempowerment.com" ] && want="$BEACON_PUBLIC"; done
    for h in $ADGUARD_CITADEL_HOSTS; do [ "$dom" = "$h.kytranempowerment.com" ] && want="$CITADEL_PUBLIC"; done
    if [ -z "$want" ]; then
      _ag_log "  ? $dom -> $ans (not in the map — REPORTED, never rewritten)"
      continue
    fi
    if [ "$ans" != "$want" ]; then
      _ag_log "  *** $dom -> $ans   (expected $want)"
      drift=$((drift+1))
    fi
  done <<< "$raw"
  _ag_log "checked $measured rewrite(s); $drift drifted"
  [ "$drift" -eq 0 ] && return 0 || return 1
}

# ---------------------------------------------------------------------------
# Does each name RESOLVE **and** SERVE? (#5246)
#
# adguard_lan_check proves the DNS answer matches the declared map. That is NOT
# proof the name works, and the difference is the whole 2026-07-26 incident:
# platform./creed./server./media. resolved to a host that was UP, the answer was
# defensible, and every layer anyone checked read healthy — but the recovery hub
# Caddy had `auto_https off` and REFUSED :443. What nobody checked was whether
# the name actually SERVED. That gap lasted ~13 hours.
#
# So this resolves through AdGuard (the resolver a LAN client uses) and then
# completes a real TLS handshake to the answer, with SNI, per hostname.
#
# THREE RULES:
#   * PER HOST. An aggregate "LAN DNS OK" is exactly what hid this for 13 hours.
#   * UNKNOWN IS NOT OK. A name we cannot measure reports ?, never a pass — same
#     rule as the backup-freshness and gov-watch ingest monitors.
#   * DETECTION ONLY. This never writes. A verify phase that repoints things is
#     how a blanket repoint sneaks back in (#5219).
#
# Probed FROM BOSTON-2 deliberately, not from the hub: with
# `userland-proxy: false` the hub cannot reach its OWN published ports via its
# public IP (the documented hairpin), so hub-fronted names would report false
# failures if probed there.
#
# Exit: 0 = every measured name served, 1 = at least one did not, 2 = nothing measurable.
# ---------------------------------------------------------------------------
ADGUARD_DNS_IP="${ADGUARD_DNS_IP:-$HUB_MESH}"

adguard_lan_serves(){
  local names="${1:-$ADGUARD_BEACON_HOSTS}" bad=0 ok=0 unknown=0
  command -v dig >/dev/null 2>&1 || { _ag_log "SKIP: dig not installed — cannot verify LAN DNS"; return 2; }
  for h in $names; do
    local fqdn="$h.kytranempowerment.com" ip tls
    ip="$(dig +short +time=3 +tries=1 "@$ADGUARD_DNS_IP" "$fqdn" A 2>/dev/null | grep -E '^[0-9.]+$' | head -1)"
    if [ -z "$ip" ]; then
      _ag_log "  ? $fqdn — no answer from AdGuard (UNKNOWN, not a pass)"
      unknown=$((unknown+1)); continue
    fi
    # A TLS handshake, not a port knock: :443 open but not terminating TLS is
    # still broken for the user.
    if echo | timeout 8 openssl s_client -connect "$ip:443" -servername "$fqdn" >/dev/null 2>&1; then
      _ag_log "  OK $fqdn -> $ip (resolves AND serves TLS)"
      ok=$((ok+1))
    else
      _ag_log "  *** $fqdn -> $ip RESOLVES BUT DOES NOT SERVE TLS on 443"
      bad=$((bad+1))
    fi
  done
  _ag_log "serve-check: $ok serving, $bad broken, $unknown unknown"
  [ "$bad" -gt 0 ] && return 1
  [ "$ok" -eq 0 ] && return 2
  return 0
}

# Repoint drifted hosts, ONE AT A TIME, each gated on a TLS probe of the target.
adguard_lan_restore(){
  local raw fixed=0 skipped=0
  raw="$(_ag_list)"
  if [ -z "$raw" ] || echo "$raw" | grep -q '^ERR'; then
    _ag_log "could not read AdGuard rewrites — refusing to write anything"
    return 2
  fi
  while read -r dom ans; do
    [ -n "$dom" ] || continue
    case " $ADGUARD_PROTECTED " in *" $dom "*) continue ;; esac
    local want=""
    for h in $ADGUARD_BEACON_HOSTS;  do [ "$dom" = "$h.kytranempowerment.com" ] && want="$BEACON_PUBLIC"; done
    for h in $ADGUARD_CITADEL_HOSTS; do [ "$dom" = "$h.kytranempowerment.com" ] && want="$CITADEL_PUBLIC"; done
    [ -n "$want" ] || { skipped=$((skipped+1)); continue; }
    [ "$ans" = "$want" ] && continue

    if ! _ag_tls_ok "$want"; then
      _ag_log "  REFUSING $dom -> $want : no :443 listener there (ADR-009 / #5219)"
      skipped=$((skipped+1)); continue
    fi
    if _ag_api "
try:
    call('/control/rewrite/delete',{'domain':'$dom','answer':'$ans'})
    call('/control/rewrite/add',   {'domain':'$dom','answer':'$want'})
    print('OK')
except Exception as e:
    print('ERR',type(e).__name__,e)
" | grep -q OK; then
      _ag_log "  $dom : $ans -> $want"
      fixed=$((fixed+1))
    else
      _ag_log "  WARN: failed to repoint $dom (left on $ans)"
      skipped=$((skipped+1))
    fi
  done <<< "$raw"
  _ag_log "repointed $fixed, skipped/unmapped $skipped"
  return 0
}

# Standalone use; also source-able by force_reset_to_hub.sh / failback.sh.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  if [ "${1:-}" = "--serves" ]; then
    _ag_log "resolve-AND-serve check (detection only, never writes)"
    adguard_lan_serves
  elif [ "${1:-}" = "--apply" ]; then
    adguard_lan_restore
    _ag_log "re-checking after apply..."
    adguard_lan_check
  else
    _ag_log "DETECT ONLY (pass --apply to write)"
    adguard_lan_check
  fi
fi
