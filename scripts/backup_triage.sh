#!/usr/bin/env bash
# scripts/backup_triage.sh
# Simple daily backup used during the Phase-0 triage window.
# Replaces the broken create_backup_programmatic() call in the crontab
# until the full scripts/backup/ system lands (Phases 1–6).
#
# Uses the direct, proven approach:
#   - pg_dump -Fc -Z 6 via docker exec archie_database
#   - tar -czf for code
#   - git bundle --all for git histories
#   - tar -czf for config (plaintext — encryption lands in Phase 2)
#   - pipe to /mnt/external-backup via docker exec archie_platform (USB is root-owned)
#
# Runs as the kytran user (user crontab); no sudo required.
#
# Spec:  docs/superpowers/specs/2026-04-16-backup-system-design.md
# Plan:  docs/superpowers/plans/2026-04-16-backup-system-redesign.md

set -euo pipefail

LOG=/var/log/archie_backup.log
# Fallback if /var/log is not writable by kytran
if ! [[ -w /var/log ]]; then
    LOG=/tmp/archie_backup.log
fi

log() {
    echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG" >&2
}

TS=$(date -u +%Y%m%d_%H%M%S)
RUN="/mnt/data2/backups/${TS}_Daily_Triage"
STATUS=success
FAIL_REASON=""

log "=== backup_triage.sh START ts=$TS run=$RUN ==="

trap 'log "=== backup_triage.sh END status=$STATUS ==="' EXIT

# Load BACKUP_CONFIG_PASSPHRASE from .env — cron runs with a bare env so the var
# is otherwise unset, which silently skipped config encryption and shipped
# PLAINTEXT secrets (.env + secrets/) to the DR node every night (#4048). Parse
# the value literally; NEVER `source` .env (it has unquoted secrets with shell
# metacharacters that break sourcing with exit 127, #4045).
if [[ -z "${BACKUP_CONFIG_PASSPHRASE:-}" && -f /mnt/archie_brain/.env ]]; then
    BACKUP_CONFIG_PASSPHRASE="$(sed -n 's/^BACKUP_CONFIG_PASSPHRASE=//p' /mnt/archie_brain/.env | head -1)"
    BACKUP_CONFIG_PASSPHRASE="${BACKUP_CONFIG_PASSPHRASE%\"}"; BACKUP_CONFIG_PASSPHRASE="${BACKUP_CONFIG_PASSPHRASE#\"}"
    export BACKUP_CONFIG_PASSPHRASE
fi

mkdir -p "$RUN"/{database,code,gitbundles,config}

# All temp for this backup run goes to the backup disk, NOT the intentional 2G /tmp tmpfs:
# a full /tmp (e.g. Codex worktrees, #4045) otherwise breaks git bundle / tar / etc. Scoped to
# this cron process only (export does not leak to other processes).
export TMPDIR="$(dirname "$RUN")/.tmp"; mkdir -p "$TMPDIR"

# ----- [1/4] DB dump -----
log "[1/4] DB dump via docker exec archie_database pg_dump..."
if docker exec archie_database pg_dump -U archie -d archie -Fc -Z 6 > "$RUN/database/archie_${TS}.dump" 2>>"$LOG"; then
    SZ=$(stat -c %s "$RUN/database/archie_${TS}.dump")
    log "  DB dump OK ($SZ bytes)"
else
    STATUS=failed; FAIL_REASON="pg_dump failed"
    log "  DB dump FAILED — see log"
fi
# wtf DB (secondary; non-fatal) — WTF news data lives in a separate `wtf` DB on hub postgres
if docker exec archie_database pg_dump -U archie -d wtf -Fc -Z 6 > "$RUN/database/wtf_${TS}.dump" 2>>"$LOG"; then
    log "  wtf DB dump OK ($(stat -c %s "$RUN/database/wtf_${TS}.dump") bytes)"
else
    log "  wtf DB dump FAILED (non-fatal; archie dump is the primary)"
    rm -f "$RUN/database/wtf_${TS}.dump"
fi

# CREED DB (standalone creed_postgres — non-fatal; data used by failover.sh 4e)
if docker ps --filter name=creed_postgres --filter status=running -q 2>/dev/null | grep -q .; then
    if docker exec creed_postgres pg_dump -U creed -d creed -Fc -Z 6 \
           > "$RUN/database/creed_${TS}.dump" 2>>"$LOG"; then
        log "  CREED DB dump OK ($(stat -c %s "$RUN/database/creed_${TS}.dump") bytes)"
    else
        log "  CREED DB dump FAILED (non-fatal)"
        rm -f "$RUN/database/creed_${TS}.dump"
    fi
fi

# ----- [2/4] Code tar -----
# Judge this step by the ARTIFACT, not tar's exit code (#5020).
#
# tar exits non-zero for UNREADABLE FILES even when the archive it produced is complete and
# valid. Nine consecutive nightlies were marked 'failed' by the old `if tar; then` because a
# handful of root-owned .ruff_cache entries returned "Cannot open: Permission denied" —
# lint-cache junk that has no business in a backup. Every one of those runs had in fact
# written a good 875 MB archive (verified: 5,682 entries, gzip -t OK).
#
# The cost of that false failure was NOT cosmetic: one failed component marks the whole run
# failed, which skips tier sync + retention (USB/gdrive/DR never received a perfectly good
# backup) and makes backup_log report NO restore point — which in turn blocks every
# medium-risk deploy via the W.A.R.D.E.N. freshness gate.
#
# So: exclude the cache dirs that caused it, and then VERIFY the tarball. A genuinely broken
# archive still fails — gzip -t is the check, not a blind ignore of the exit code.
log "[2/4] Code tar..."
TAR_RC=0
tar -czf "$RUN/code/archie_code_${TS}.tar.gz" \
    --exclude=".git" --exclude="__pycache__" --exclude="node_modules" \
    --exclude=".venv" --exclude="*.pyc" \
    --exclude=".ruff_cache" --exclude=".pytest_cache" --exclude=".mypy_cache" \
    -C /mnt/archie_brain platform_v2 ai_bridge scripts database/migrations 2>>"$LOG" || TAR_RC=$?

if [ -s "$RUN/code/archie_code_${TS}.tar.gz" ] && gzip -t "$RUN/code/archie_code_${TS}.tar.gz" 2>>"$LOG"; then
    SZ=$(stat -c %s "$RUN/code/archie_code_${TS}.tar.gz")
    if [ "$TAR_RC" -ne 0 ]; then
        # Archive is good; tar merely complained. Say so loudly enough to be fixed, but do
        # NOT condemn the run — see the nine false failures above.
        log "  code tar OK WITH WARNINGS ($SZ bytes, tar rc=$TAR_RC — see $LOG for unreadable paths)"
    else
        log "  code tar OK ($SZ bytes)"
    fi
else
    STATUS=failed; FAIL_REASON="${FAIL_REASON}; code tar failed"
    log "  code tar FAILED (rc=$TAR_RC, archive missing or failed gzip -t)"
fi

# ----- [3/4] Git bundles -----
log "[3/4] Git bundles..."   # TMPDIR already on the backup disk (set above) so a full /tmp can't break bundling (#4045)
for repo in /mnt/archie_brain /mnt/archie_brain/kytran-business-suite /mnt/archie_brain/kytran-server-manager /mnt/archie_brain/kytran-creed; do
    name=$(basename "$repo" | sed 's/kytran-//')
    if [[ ! -d "$repo/.git" ]]; then
        log "  skip $name (no .git)"
        continue
    fi
    if git -C "$repo" bundle create "$RUN/gitbundles/${name}_${TS}.bundle" --all >>"$LOG" 2>&1; then
        SZ=$(stat -c %s "$RUN/gitbundles/${name}_${TS}.bundle")
        log "  bundle $name OK ($SZ bytes)"
    else
        STATUS=failed; FAIL_REASON="${FAIL_REASON}; $name bundle failed"
        log "  bundle $name FAILED"
    fi
done

# ----- [4/4] Config tar — AES-256-CBC encrypted (BACKUP_CONFIG_PASSPHRASE) -----
# Decrypt: scripts/backup/decrypt_restore.sh <file>.enc BACKUP_CONFIG_PASSPHRASE
log "[4/4] Config tar (encrypting with AES-256-CBC)..."
tar --ignore-failed-read -czf "$RUN/config/config_${TS}.tar.gz" \
    -C /mnt/archie_brain \
    .env docker-compose.yml .mcp.json CLAUDE.md \
    .claude/rules nginx secrets 2>>"$LOG" || true
if [[ -n "${BACKUP_CONFIG_PASSPHRASE:-}" ]] && [[ -s "$RUN/config/config_${TS}.tar.gz" ]]; then
    if openssl enc -aes-256-cbc -pbkdf2 -iter 200000 \
        -in  "$RUN/config/config_${TS}.tar.gz" \
        -out "$RUN/config/config_${TS}.tar.gz.enc" \
        -pass env:BACKUP_CONFIG_PASSPHRASE 2>>"$LOG"; then
        rm -f "$RUN/config/config_${TS}.tar.gz"
        SZ=$(stat -c %s "$RUN/config/config_${TS}.tar.gz.enc" 2>/dev/null || echo 0)
        log "  config tar encrypted OK ($SZ bytes, .tar.gz.enc)"
    else
        rm -f "$RUN/config/config_${TS}.tar.gz"
        STATUS=failed; FAIL_REASON="${FAIL_REASON}; config encrypt failed — plaintext removed"
        log "  ERROR: config tar encryption FAILED — plaintext tar REMOVED (refused to ship secrets unencrypted) (#4048)"
    fi
else
    # No passphrase even after the .env load → do NOT leave/ship plaintext
    # secrets. Remove the plaintext tarball and fail loudly (#4048).
    rm -f "$RUN/config/config_${TS}.tar.gz"
    STATUS=failed; FAIL_REASON="${FAIL_REASON}; BACKUP_CONFIG_PASSPHRASE missing — config NOT backed up (refused to ship plaintext secrets)"
    log "  ERROR: BACKUP_CONFIG_PASSPHRASE not set after .env load — config tar REMOVED (refused to ship plaintext secrets). Set it in /mnt/archie_brain/.env."
fi

# ----- metadata.json + rollback.sh (self-describing + self-recovering, #4049) -----
# Runs after all components exist and BEFORE the USB/DR copy so both files ship with the backup.
log "Writing metadata.json + rollback.sh..."
if "$(dirname "$0")/backup/write_backup_metadata.sh" "$RUN" >>"$LOG" 2>&1; then
    log "  metadata + rollback OK"
else
    log "  metadata/rollback generation FAILED (non-fatal — backup data is unaffected)"
fi

# ----- Copy to USB via docker exec (USB is root-owned) -----
log "Copying to USB via docker exec archie_platform..."
USB_STATUS=success
if tar -C "$(dirname "$RUN")" -cf - "$(basename "$RUN")" | \
   docker exec -i archie_platform tar -C /mnt/external-backup -xf - 2>>"$LOG"; then
    log "  USB copy OK"
else
    log "  USB copy FAILED (primary copy still OK)"
    USB_STATUS=failed
fi

# Headscale data (DB + keys — enables DR Headscale standby on boston-2 for #3673)
# Extracting from Docker volume via alpine sidecar.
if docker ps --filter name=archie_headscale --filter status=running -q 2>/dev/null | grep -q .; then
    if docker run --rm \
           -v archie_headscale_data:/source:ro \
           -v "$RUN/database":/out \
           alpine tar -czf /out/headscale_${TS}.tar.gz -C /source . 2>>"$LOG"; then
        log "  Headscale data dump OK ($(stat -c %s "$RUN/database/headscale_${TS}.tar.gz") bytes)"
    else
        log "  Headscale data dump FAILED (non-fatal)"
        rm -f "$RUN/database/headscale_${TS}.tar.gz"
    fi
fi

# ----- Ship to DR node boston-2 (off-hub cold copy for DRP, mesh-only) -----
# Gives the DR node a local Tier-2 cold restore artifact independent of the hub,
# and a warm starting point that shortens failback re-clone. Mesh IP only
# (100.64.0.10) — never a public hostname. Non-fatal: primary+USB still stand.
DR_STATUS=success
DR_NODE=100.64.0.10
DR_DIR=/opt/archie-dr/backups
SSH_KEY=/home/kytran/.ssh/id_ed25519
DR_KEEP=7
log "Shipping to DR node boston-2 (${DR_NODE}) via rsync over mesh..."
if [[ -f "$SSH_KEY" ]] && rsync -a \
     -e "ssh -i $SSH_KEY -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new" \
     "$RUN" "root@${DR_NODE}:${DR_DIR}/" >>"$LOG" 2>&1; then
    log "  DR ship OK -> ${DR_NODE}:${DR_DIR}/$(basename "$RUN")"
    # Prune DR copies (keep most-recent ${DR_KEEP})
    ssh -i "$SSH_KEY" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new "root@${DR_NODE}" \
        "ls -td ${DR_DIR}/*_Daily_Triage 2>/dev/null | tail -n +$((DR_KEEP+1)) | xargs -r rm -rf" >>"$LOG" 2>&1 || true
else
    log "  DR ship FAILED (primary+USB copies still OK)"
    DR_STATUS=failed
fi

# ----- Refresh DR warm-standby source on boston-2 (prevent staged-source drift) -----
# Mirrors the LIVE bind-mounted source (platform_v2 + ai_bridge + scripts) into the DR
# node's staged platform so a real failover boots current code. (ai_bridge drift was the
# Phase-5b boot blocker — KB #270232.) scripts/ carries the backup/restore/DR tooling
# (restore_db.sh, write_backup_metadata.sh, sandbox worker) the platform now references —
# otherwise it drifts stale on boston-2 (#4036). Non-fatal; only when the DR node is reachable.
DR_PLATFORM=/opt/archie-dr/platform
if [[ "${DR_STATUS:-failed}" == "success" ]]; then
    log "Refreshing DR warm-standby source on boston-2 (platform_v2 + ai_bridge + scripts)..."
    for sub in platform_v2 ai_bridge scripts; do
        if rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' \
             --exclude='*.log' --exclude='opencode' \
             -e "ssh -i $SSH_KEY -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new" \
             "/mnt/archie_brain/$sub/" "root@${DR_NODE}:${DR_PLATFORM}/$sub/" >>"$LOG" 2>&1; then
            log "  refreshed $sub"
        else
            log "  WARN: $sub refresh failed (non-fatal)"
        fi
    done
fi

# Refresh CREED source on boston-2 (enables failover.sh 4e to start CREED there)
# Excludes data/ so postgres bind-mount on boston-2 is NOT overwritten.
# secrets/ IS included — boston-2 is a trusted DR node and needs the DB password.
if [[ "${DR_STATUS:-failed}" == "success" ]]; then
    log "Refreshing CREED source on boston-2..."
    if rsync -a --delete \
             --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
             --exclude='data/' \
             -e "ssh -i $SSH_KEY -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new" \
             "/mnt/archie_brain/kytran-creed/" "root@${DR_NODE}:/opt/archie-products/creed/" >>"$LOG" 2>&1; then
        log "  CREED source refreshed on boston-2 (/opt/archie-products/creed/)"
    else
        log "  WARN: CREED source refresh failed (non-fatal; failover.sh 4e will warn if missing)"
    fi
fi

# ----- Local Daily_Triage prune (the GFS engine below skips these; see note) -----
# retention_prune.py explicitly skips *_Daily_Triage (_shared.py: "Skip Daily_Triage
# dirs -- managed by scripts/backup_triage.sh"), and the DR prune above only trims
# the remote copies on the DR node. Nothing ever removed the LOCAL copies, so
# /mnt/data2/backups accumulated one set per run forever: 30 sets / ~120 GB on
# 2026-10-02, with /mnt/data2 at 96% (82 GB free). Keep LOCAL_KEEP in step with
# DR_KEEP so both tiers retain the same window.
LOCAL_KEEP=7
log "Pruning local Daily_Triage sets (keep ${LOCAL_KEEP})..."
PRUNED=$(ls -td /mnt/data2/backups/*_Daily_Triage 2>/dev/null | tail -n +$((LOCAL_KEEP+1)) | wc -l)
if [[ "$PRUNED" -gt 0 ]]; then
    ls -td /mnt/data2/backups/*_Daily_Triage 2>/dev/null | tail -n +$((LOCAL_KEEP+1)) | xargs -r rm -rf
    log "  pruned ${PRUNED} local Daily_Triage set(s)"
else
    log "  nothing to prune"
fi

# ----- Retention: canonical GFS engine (per-component daily/weekly/monthly, all tiers) -----
# Single source of truth = scripts/backup/retention_prune.py. The old inline keep-14 and the
# weekly module job backup_retention_prune are RETIRED — #4051. retention_prune.py keeps the DB
# dumps longest (30 daily) and trims bulkier components, across primary + USB. Non-fatal.
log "Retention: GFS prune via retention_prune.py..."
if python3 "$(dirname "$0")/backup/retention_prune.py" >>"$LOG" 2>&1; then
    log "  retention prune OK"
else
    log "  WARN: retention prune had errors (non-fatal — backup data unaffected)"
fi

# ----- Record to backup_log (new canonical schema from Phase 1 Task 2) -----
# If the schema migration hasn't run yet, fall back to the legacy schema.
SZ_TOTAL=$(du -sb "$RUN" 2>/dev/null | awk '{print $1}')
# Stamp the CURRENT platform build (#5087) so the nightly rows show "Build #N" in the Backups
# list instead of "Build #-". Read-only — the button/programmatic path owns the counter; a
# nightly records the build it ran under, never bumps it. Guard with [[ -r ]] + a direct read
# (NOT `cat file | tr`): this script runs `set -euo pipefail`, so a cat of a MISSING file fails
# the pipeline and would abort the nightly. Digits-only, so an empty file yields '' -> SQL NULL.
BUILD=""
if [[ -r /mnt/data2/backups/.current_build ]]; then
    BUILD=$(tr -dc '0-9' < /mnt/data2/backups/.current_build)
fi
BUILD_SQL="NULL"; [[ -n "$BUILD" ]] && BUILD_SQL="$BUILD"
docker exec -i archie_database psql -U archie -d archie <<SQL >>"$LOG" 2>&1 || true
DO \$\$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='backup_log' AND column_name='component') THEN
        INSERT INTO backup_log (component, tier, status, file_path, size_bytes, notes, build_number, created_at)
        VALUES ('daily_triage', 'primary', '${STATUS}', '${RUN}', ${SZ_TOTAL}, 'backup_triage.sh', ${BUILD_SQL}, NOW());
        -- USB tier: lets backup_service.get_health_summary() track USB staleness
        INSERT INTO backup_log (component, tier, status, file_path, size_bytes, notes, build_number, created_at)
        VALUES ('daily_triage', 'usb', '${USB_STATUS}', '/mnt/external-backup/$(basename "${RUN}")', ${SZ_TOTAL}, 'backup_triage.sh USB copy', ${BUILD_SQL}, NOW());
        -- DR tier: off-hub cold copy on boston-2 (mesh); lets get_health_summary() track DR staleness
        INSERT INTO backup_log (component, tier, status, file_path, size_bytes, notes, build_number, created_at)
        VALUES ('daily_triage', 'dr', '${DR_STATUS}', 'boston-2:${DR_DIR}/$(basename "${RUN}")', ${SZ_TOTAL}, 'backup_triage.sh DR ship (boston-2 mesh 100.64.0.10)', ${BUILD_SQL}, NOW());
    ELSE
        INSERT INTO backup_log (backup_type, file_path, file_size_bytes, status, error_message, completed_at, created_at)
        VALUES ('daily_triage', '${RUN}', ${SZ_TOTAL}, '${STATUS}', NULLIF('${FAIL_REASON}', ''), NOW(), NOW());
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'could not log to backup_log: %', SQLERRM;
END \$\$;
SQL

log "done: status=$STATUS size=$SZ_TOTAL reason='${FAIL_REASON}'"
if [[ "$STATUS" != "success" ]]; then
    exit 1
fi
