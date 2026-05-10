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

mkdir -p "$RUN"/{database,code,gitbundles,config}

# ----- [1/4] DB dump -----
log "[1/4] DB dump via docker exec archie_database pg_dump..."
if docker exec archie_database pg_dump -U archie -d archie -Fc -Z 6 > "$RUN/database/archie_${TS}.dump" 2>>"$LOG"; then
    SZ=$(stat -c %s "$RUN/database/archie_${TS}.dump")
    log "  DB dump OK ($SZ bytes)"
else
    STATUS=failed; FAIL_REASON="pg_dump failed"
    log "  DB dump FAILED — see log"
fi

# ----- [2/4] Code tar -----
log "[2/4] Code tar..."
if tar -czf "$RUN/code/archie_code_${TS}.tar.gz" \
    --exclude=".git" --exclude="__pycache__" --exclude="node_modules" \
    --exclude=".venv" --exclude="*.pyc" \
    -C /mnt/archie_brain platform_v2 ai_bridge scripts database/migrations 2>>"$LOG"; then
    SZ=$(stat -c %s "$RUN/code/archie_code_${TS}.tar.gz")
    log "  code tar OK ($SZ bytes)"
else
    STATUS=failed; FAIL_REASON="${FAIL_REASON}; code tar failed"
    log "  code tar FAILED"
fi

# ----- [3/4] Git bundles -----
log "[3/4] Git bundles..."
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

# ----- [4/4] Config tar (plaintext; Phase 2 Task 8 adds encryption) -----
log "[4/4] Config tar..."
tar --ignore-failed-read -czf "$RUN/config/config_${TS}.tar.gz" \
    -C /mnt/archie_brain \
    .env docker-compose.yml .mcp.json CLAUDE.md \
    .claude/rules nginx secrets 2>>"$LOG" || true
SZ=$(stat -c %s "$RUN/config/config_${TS}.tar.gz" 2>/dev/null || echo 0)
log "  config tar OK ($SZ bytes)"

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

# ----- Retention: keep 14 most-recent triage dailies on primary, 7 on USB -----
log "Pruning old primary triage dirs (keep 14)..."
ls -td /mnt/data2/backups/*_Daily_Triage 2>/dev/null | tail -n +15 | xargs -r rm -rf
log "Pruning old USB triage dirs (keep 7)..."
docker exec archie_platform bash -c 'ls -td /mnt/external-backup/*_Daily_Triage 2>/dev/null | tail -n +8 | xargs -r rm -rf' 2>>"$LOG" || true

# ----- Record to backup_log (new canonical schema from Phase 1 Task 2) -----
# If the schema migration hasn't run yet, fall back to the legacy schema.
SZ_TOTAL=$(du -sb "$RUN" 2>/dev/null | awk '{print $1}')
docker exec -i archie_database psql -U archie -d archie <<SQL >>"$LOG" 2>&1 || true
DO \$\$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='backup_log' AND column_name='component') THEN
        INSERT INTO backup_log (component, tier, status, file_path, size_bytes, notes, created_at)
        VALUES ('daily_triage', 'primary', '${STATUS}', '${RUN}', ${SZ_TOTAL}, 'backup_triage.sh', NOW());
        -- USB tier: lets backup_service.get_health_summary() track USB staleness
        INSERT INTO backup_log (component, tier, status, file_path, size_bytes, notes, created_at)
        VALUES ('daily_triage', 'usb', '${USB_STATUS}', '/mnt/external-backup/$(basename "${RUN}")', ${SZ_TOTAL}, 'backup_triage.sh USB copy', NOW());
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
