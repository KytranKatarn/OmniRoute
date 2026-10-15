#!/usr/bin/env bash
# env_guard.sh - keep the root compose .env from being silently clobbered (tasks 7184, 2026-10-09 and 2026-10-14).
#
# Twice the file was overwritten by a single write down to 2 lines (51 bytes), which breaks every `docker compose` call
# (`required variable BROWSER_VNC_PASSWORD is missing`). The writer was never found, so this guard contains the damage instead.
#
# Every run:
#   1. HEALTHY  = every `${VAR:?...}` variable that docker-compose.yml requires has a value, AND size >= 50% of the last good snapshot.
#      Healthy -> snapshot it (only if the content changed), keep the newest KEEP snapshots.
#   2. UNHEALTHY -> keep the bad file as .env.clobbered-<ts> (evidence: names only are logged, never values), restore the newest
#      healthy snapshot atomically, validate with `docker compose config -q`, and log it. A deliberate shrink is still possible by
#      removing the snapshots first; a real edit that keeps every required variable and stays above 50% is never touched.
#
# Secrets: this script never prints a value. Snapshots live OUTSIDE the repo in a 0700 dir, files 0600.
set -euo pipefail

ROOT="${ENV_GUARD_ROOT:-/mnt/archie_brain}"
ENV_FILE="$ROOT/.env"
COMPOSE="$ROOT/docker-compose.yml"
STATE="${ENV_GUARD_DIR:-$HOME/.local/state/archie-env-guard}"
KEEP="${ENV_GUARD_KEEP:-40}"
LOG="$STATE/guard.log"

umask 077
mkdir -p "$STATE"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >>"$LOG"; }

required_names() {
    # `${NAME:?msg}` is compose's "must be set" form.
    grep -o '\${[A-Z_][A-Z0-9_]*:?' "$COMPOSE" | sed 's/^\${//; s/:?$//' | sort -u
}

has_value() { # $1=file $2=name -> 0 when NAME= has a non-empty value
    local v
    v="$(sed -n "s/^$2=//p" "$1" | head -1 | tr -d '"'"'"'\r')"
    [[ -n "$v" ]]
}

healthy() { # $1=file
    local f="$1" n
    [[ -s "$f" ]] || return 1
    while read -r n; do
        [[ -z "$n" ]] && continue
        has_value "$f" "$n" || { MISSING="$n"; return 1; }
    done < <(required_names)
    return 0
}

latest_snapshot() { ls -1t "$STATE"/env.snap.* 2>/dev/null | head -1 || true; }

MISSING=""
LAST="$(latest_snapshot)"
CUR_SIZE=$(stat -c %s "$ENV_FILE" 2>/dev/null || echo 0)
LAST_SIZE=0
[[ -n "$LAST" ]] && LAST_SIZE=$(stat -c %s "$LAST")

shrunk=0
if (( LAST_SIZE > 0 )) && (( CUR_SIZE * 2 < LAST_SIZE )); then shrunk=1; fi

if healthy "$ENV_FILE" && (( shrunk == 0 )); then
    new_hash=$(sha256sum "$ENV_FILE" | cut -c1-16)
    if [[ -z "$LAST" ]] || [[ "$(sha256sum "$LAST" | cut -c1-16)" != "$new_hash" ]]; then
        cp "$ENV_FILE" "$STATE/env.snap.$(date +%Y%m%d-%H%M%S).$new_hash"
        chmod 600 "$STATE"/env.snap.*
        log "snapshot ok ($CUR_SIZE bytes, $(grep -c '^[A-Za-z_][A-Za-z0-9_]*=' "$ENV_FILE") vars)"
    fi
    # prune
    ls -1t "$STATE"/env.snap.* 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f --
    exit 0
fi

# ---- unhealthy ----
[[ -n "$LAST" ]] || { log "UNHEALTHY but no snapshot to restore from (missing='${MISSING:-size}')"; exit 1; }
healthy "$LAST" || { log "UNHEALTHY and newest snapshot is not healthy either - refusing to restore"; exit 1; }

ts=$(date +%Y%m%d-%H%M%S)
bad="$ROOT/.env.clobbered-$ts"
cp -p "$ENV_FILE" "$bad" 2>/dev/null || true
chmod 600 "$bad" 2>/dev/null || true
names=$(sed -n 's/^\(export \)\?\([A-Za-z_][A-Za-z0-9_]*\)=.*/\2/p' "$ENV_FILE" 2>/dev/null | tr '\n' ' ')
log "CLOBBER detected: size=$CUR_SIZE (last good $LAST_SIZE) missing='${MISSING:-none}' mtime=$(stat -c %y "$ENV_FILE" 2>/dev/null) owner=$(stat -c %U "$ENV_FILE" 2>/dev/null) names=[$names] kept=$bad"

tmp="$ENV_FILE.guard-tmp.$$"
cp "$LAST" "$tmp"
chmod 660 "$tmp"
mv -f "$tmp" "$ENV_FILE"
if (cd "$ROOT" && docker compose config -q >/dev/null 2>&1); then
    log "RESTORED from $(basename "$LAST"); docker compose config validates"
else
    log "RESTORED from $(basename "$LAST") but docker compose config did NOT validate - needs a human"
    exit 1
fi
