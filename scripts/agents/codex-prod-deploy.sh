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
# NOTE (#5980): `docker exec -i` keeps stdin open and DRAINS it. Called from
# inside `echo "$ROWS" | while read ...`, it swallowed the remaining rows, so
# the loop silently processed exactly ONE row per invocation. `</dev/null`
# gives it nothing to eat; every call here passes -c and needs no stdin.
psql_q(){ docker exec -i archie_database psql -U archie -d archie -tA "$@" </dev/null; }

tg(){ # tg <title> <msg> — Telegram via the platform service (argv; no interpolation)
  docker exec archie_platform python3 -c 'import sys; sys.path.insert(0,"/app")
from services import telegram_service as t
t.send_system(sys.argv[1], sys.argv[2])' "$1" "$2" >>"$LOG" 2>&1 || true
}

ROWS="$(psql_q -F'|' -c "
  SELECT id, action_data->>'pr_number', COALESCE(action_data->>'module',''), COALESCE(execution_result->>'merge_sha','')
  FROM autonomy_approval_queue
  WHERE action_type='codex_promote' AND execution_result->>'deploy_pending'='true'
  ORDER BY id;" 2>>"$LOG" || true)"
[ -z "$ROWS" ] && exit 0

echo "$ROWS" | while IFS='|' read -r AID PR MODULE MERGE_SHA; do
  [ -z "${AID:-}" ] && continue
  log "deploy-pending: approval #$AID PR #$PR module='$MODULE' sha=${MERGE_SHA:0:7} (LIVE=$LIVE)"
  # SECURITY: strict allow-lists before any use (injection defence-in-depth).
  if [ -n "$MODULE" ] && ! printf '%s' "$MODULE" | grep -qE '^[a-z0-9_-]{1,40}$'; then
    log "REJECT #$AID — invalid module '$MODULE'"; continue
  fi
  if ! printf '%s' "$PR" | grep -qE '^[0-9]+$'; then
    log "REJECT #$AID — invalid pr_number '$PR'"; continue
  fi
  if [ -n "$MERGE_SHA" ] && ! printf '%s' "$MERGE_SHA" | grep -qE '^[0-9a-f]{7,40}$'; then
    log "REJECT #$AID — invalid merge_sha '$MERGE_SHA'"; continue
  fi
  cd "$REPO"

  # RECONCILE — runs in DRY-RUN too (#5980). If this merge SHA is already an
  # ancestor of main, the code IS deployed: the flag is stale, not a backlog.
  # The clear below used to live ONLY inside the LIVE branch, and
  # CODEX_DEPLOY_LIVE has never been set anywhere, so it never ran. Fourteen
  # approvals whose PRs merged in June 2026 were re-detected every 2 minutes,
  # growing an 18 MB log and burying any REAL pending deploy among permanent
  # false positives. Fails CLOSED: an absent or unknown SHA keeps the flag.
  if [ -n "$MERGE_SHA" ] && git cat-file -e "${MERGE_SHA}^{commit}" 2>/dev/null \
     && git merge-base --is-ancestor "$MERGE_SHA" main 2>/dev/null; then
    log "RECONCILE #$AID — ${MERGE_SHA:0:7} already an ancestor of main; clearing stale deploy_pending"
    psql_q -c "UPDATE autonomy_approval_queue SET execution_result=jsonb_set(COALESCE(execution_result,'{}'),'{deploy_pending}','false'), updated_at=NOW() WHERE id=$AID;" >>"$LOG" 2>&1 || true
    continue
  fi

  # SAFETY GUARD: never clobber active dev work. Only DEFER on uncommitted TRACKED
  # changes (which the `git reset --hard` below would discard). Ignore untracked files
  # (reports/plans are never clobbered by a reset) and the auto-generated
  # learned-skills.md (Job #54 churns it constantly) — otherwise the poller defers
  # forever on harmless artifacts and NOTHING ever deploys (the 2026-06-12 backlog).
  BR="$(git rev-parse --abbrev-ref HEAD)"
  DIRTY="$(git status --porcelain --untracked-files=no | grep -v 'learned-skills\.md' || true)"
  if [ "$BR" != "main" ] || [ -n "$DIRTY" ]; then
    log "DEFER #$AID — uncommitted tracked changes on host tree (branch=$BR); retry next cycle"
    continue
  fi

  if [ "$LIVE" != "1" ]; then
    log "DRY-RUN #$AID — would: git reset origin/main + restart archie_platform + health-gate + verify /tools/$MODULE + clear flag"
    continue
  fi

  # ---- LIVE deploy (pinned to the APPROVED merge SHA — no ride-along of later
  #      main commits without a fresh Telegram approval) ----
  PREV="$(git rev-parse HEAD)"
  git fetch origin -q
  if [ -z "$MERGE_SHA" ] || ! git merge-base --is-ancestor "$MERGE_SHA" origin/main 2>/dev/null; then
    log "REFUSE #$AID — merge_sha '${MERGE_SHA:-<none>}' not an ancestor of origin/main; re-approval required"
    tg "Codex deploy REFUSED" "PR #$PR: recorded merge_sha not on main — needs a fresh Telegram approval."
    continue
  fi
  git reset --hard "$MERGE_SHA" -q
  NEW="$(git rev-parse --short HEAD)"
  log "deploying approved sha $NEW (was ${PREV:0:7}) — restarting archie_platform..."
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
    CODE="$(python3 -c 'import urllib.request,urllib.error,sys
try: print(urllib.request.urlopen(sys.argv[1],timeout=20).status)
except urllib.error.HTTPError as e: print(e.code)
except Exception: print("down")' "$URL" 2>/dev/null || echo err)"
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
