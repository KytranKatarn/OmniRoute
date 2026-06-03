#!/bin/bash
# ============================================================================
# A.R.C.H.I.E. DR — shared Telegram alert helper (sourced by failover.sh and
# the Phase 7 watchdog). Extracted from failover.sh so there is ONE
# implementation (DRY). Behaviour is byte-identical to the original.
#
#   source "$DR/tg_notify.sh"
#   tg_notify "some <b>message</b>"
#
# SELF-CONTAINED: sources $DR/.telegram_env (TELEGRAM_BOT_TOKEN +
# TELEGRAM_CHAT_ID; chmod 600, boston-2-only) — mirrors the .hostinger_token
# pattern. Outbound push works even though the long-poll bot is off
# (ARCHIE_RUN_TELEGRAM=0): sendMessage needs only the token + chat_id. Depends
# on NOTHING from the hub (no container, no DB, no platform import) so the FIRST
# alert fires before the standby is even up. Always non-fatal: a Telegram
# failure NEVER aborts the caller.
# ============================================================================

# Default DR root if the caller did not set it. (failover.sh sets DR=/opt/archie-dr
# before sourcing; standalone callers fall back to the same path.)
DR="${DR:-/opt/archie-dr}"

# Fallback logger — only define if the caller has not already provided log().
if ! declare -F log >/dev/null 2>&1; then
  log(){ echo "[$(date -u +%H:%M:%S)] $*"; }
fi

# tg_notify "text" [inline_keyboard_json]
# Optional 2nd arg = a JSON array-of-rows for an inline keyboard, e.g.
#   '[[{"text":"✅ Proceed","callback_data":"dr_proceed"}]]'
# When given, the message carries tappable buttons. The button presses are read
# back by the watchdog's poll_action() via getUpdates — handled ON boston-2, so
# they work during a hub outage (the hub's own bot is down).
tg_notify(){
  local text="$1" keyboard="${2:-}"
  [ -f "$DR/.telegram_env" ] || { log "  (no $DR/.telegram_env — skipping Telegram alert)"; return 0; }
  # shellcheck disable=SC1091
  . "$DR/.telegram_env"
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] \
    || { log "  (Telegram token/chat unset — skipping alert)"; return 0; }
  TG_TOKEN="$TELEGRAM_BOT_TOKEN" TG_CHAT="$TELEGRAM_CHAT_ID" TG_TEXT="$text" TG_KB="$keyboard" python3 - <<'PY' 2>/dev/null \
    && log "  (Telegram alert sent)" || log "  (Telegram send failed — non-fatal)"
import os, json, urllib.request, urllib.parse
tok = os.environ["TG_TOKEN"]; chat = os.environ["TG_CHAT"]; text = os.environ["TG_TEXT"]
fields = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
kb = os.environ.get("TG_KB", "").strip()
if kb:
    fields["reply_markup"] = json.dumps({"inline_keyboard": json.loads(kb)})
data = urllib.parse.urlencode(fields).encode()
req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % tok, data=data)
urllib.request.urlopen(req, timeout=12).read()
PY
}
