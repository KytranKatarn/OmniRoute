#!/usr/bin/env bash
# codex-prod-deploy.sh — HOST poller: deploy Telegram-approved + merged Codex PRs to prod.
#
# Reads autonomy_approval_queue for codex_promote rows whose execution_result.deploy_pending
# is true (set by the agent_loop consumer after a Kytran Telegram-Approve merge), then:
#   git reset main -> docker compose restart archie_platform -> health-gate (auto-rollback to
#   the previous SHA on failure) -> verify the module page -> Telegram LIVE -> clear the flag.
#
# DRY-RUN by default. Set CODEX_DEPLOY_LIVE=1 to actually deploy.
# SAFETY: only deploys when the host tree is CLEAN and on main (never clobbers dev work).
# Cron (user crontab): */2 * * * * /mnt/archie_brain/scripts/agents/codex-prod-deploy.sh
set -euo pipefail
export PATH="/home/kytran/.local/bin:/usr/local/bin:/usr/bin:/bin"

REPO="/mnt/archie_brain"
LOG="/tmp/codex-prod-deploy.log"
LIVE="${CODEX_DEPLOY_LIVE:-0}"
HEALTH_TIMEOUT=90
log(){ echo "$(date '+%F %T') $*" >>"$LOG"; echo "$*"; }
psql_q(){ docker exec -i archie_database psql -U archie -d archie -tA "$@"; }

tg(){ # tg <title> <msg> — Telegram via the platform service (no curl)
  docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services import telegram_service as t
t.send_system('''$1''','''$2''')" >>"$LOG" 2>&1 || true
}

ROWS="$(psql_q -F'|' -c "
  SELECT id, action_data->>'pr_number', COALESCE(action_data->>'module','')
  FROM autonomy_approval_queue
  WHERE action_type='codex_promote' AND execution_result->>'deploy_pending'='true'
  ORDER BY id;" 2>>"$LOG" || true)"
[ -z "$ROWS" ] && exit 0

echo "$ROWS" | while IFS='|' read -r AID PR MODULE; do
  [ -z "${AID:-}" ] && continue
  log "deploy-pending: approval #$AID PR #$PR module='$MODULE' (LIVE=$LIVE)"
  cd "$REPO"

  # SAFETY GUARD: never clobber active dev work.
  BR="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$BR" != "main" ] || [ -n "$(git status --porcelain)" ]; then
    log "DEFER #$AID — host tree busy (branch=$BR, dirty=$([ -n "$(git status --porcelain)" ] && echo yes || echo no)); retry next cycle"
    continue
  fi

  if [ "$LIVE" != "1" ]; then
    log "DRY-RUN #$AID — would: git reset origin/main + restart archie_platform + health-gate + verify /tools/$MODULE + clear flag"
    continue
  fi

  # ---- LIVE deploy ----
  PREV="$(git rev-parse HEAD)"
  git fetch origin -q && git reset --hard origin/main -q
  NEW="$(git rev-parse --short HEAD)"
  log "deploying main $NEW (was ${PREV:0:7}) — restarting archie_platform..."
  docker compose restart archie_platform >>"$LOG" 2>&1

  # health-gate
  ok=0; waited=0
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    st="$(docker inspect --format '{{.State.Health.Status}}' archie_platform 2>/dev/null || echo none)"
    [ "$st" = "healthy" ] && { ok=1; break; }
    sleep 5; waited=$((waited+5))
  done

  if [ "$ok" = "1" ]; then
    URL="https://platform.kytranempowerment.com/tools/${MODULE:-}"
    CODE="$(python3 -c "import urllib.request,urllib.error
try: print(urllib.request.urlopen('$URL',timeout=20).status)
except urllib.error.HTTPError as e: print(e.code)
except Exception: print('down')" 2>/dev/null || echo err)"
    log "HEALTHY — verify $URL -> $CODE"
    psql_q -c "UPDATE autonomy_approval_queue SET execution_result=jsonb_set(COALESCE(execution_result,'{}'),'{deploy_pending}','false'), updated_at=NOW() WHERE id=$AID;" >>"$LOG" 2>&1 || true
    tg "Codex deploy LIVE" "PR #$PR is live in production (/tools/$MODULE, HTTP $CODE). main @ $NEW."
    log "DONE #$AID"
  else
    log "UNHEALTHY after ${HEALTH_TIMEOUT}s — ROLLING BACK to ${PREV:0:7}"
    git reset --hard "$PREV" -q
    docker compose restart archie_platform >>"$LOG" 2>&1
    tg "Codex deploy ROLLED BACK" "PR #$PR deploy was unhealthy; rolled back to ${PREV:0:7}. Flag left pending — investigate."
    log "ROLLED BACK #$AID (flag left pending)"
  fi
done
