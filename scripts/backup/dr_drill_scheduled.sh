#!/usr/bin/env bash
# scripts/backup/dr_drill_scheduled.sh — scheduled wrapper around dr_drill.sh (#4050).
#
# The Backup Manager audit (2026-06-11) found the UI restore path is broken for
# current backups and NOTHING proved that backups actually restore. dr_drill.sh
# is the authoritative, working validation (spins a throwaway Postgres, runs
# pg_restore of the latest dump, asserts knowledge_base row counts within 1% of
# production) — but it was unscheduled and silent. This wrapper runs it on a
# schedule, records the result to backup_log (component='dr_drill', tier='dr'),
# and Telegram-alerts on FAILURE so a broken backup is caught BEFORE it's needed.
#
# Pairs with dr_posture_monitor (#4031, which watches backup FRESHNESS): this
# watches RESTORABILITY.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG=/var/log/archie_backup.log
[[ -w /var/log ]] || LOG=/tmp/archie_backup.log

echo "[$(date -u +%FT%TZ)] === dr_drill_scheduled START ===" >> "$LOG"
out="$("$SCRIPT_DIR/dr_drill.sh" 2>&1)"; rc=$?
echo "$out" >> "$LOG"

status=$([[ $rc -eq 0 ]] && echo success || echo failed)
# Last ~400 chars of the drill output as a note (covers the report summary).
note="${out: -400}"

# Record to backup_log so the platform/dr_posture_monitor can see validation runs.
docker exec -i archie_database psql -U archie -d archie -v ON_ERROR_STOP=0 \
    -c "INSERT INTO backup_log (component, tier, status, notes, created_at)
        VALUES ('dr_drill', 'dr', '$status', \$note\$${note}\$note\$, NOW())" \
    >/dev/null 2>&1 || echo "[$(date -u +%FT%TZ)] WARN: dr_drill backup_log insert failed" >> "$LOG"

if [[ $rc -ne 0 ]]; then
    # Alert via the platform's unified Telegram channel (cooldown-gated).
    docker exec archie_platform python3 - <<'PYEOF' >/dev/null 2>&1 || true
import sys
sys.path.insert(0, "/app")
try:
    from services.telegram_service import send_system
    send_system(
        "DR drill FAILED — backups may not restore",
        "Scheduled restore-validation (dr_drill.sh) FAILED. The latest DB dump did "
        "NOT pg_restore to within 1% of production knowledge_base row counts. A real "
        "DR restore may be at risk — investigate scripts/backup/dr_reports/ on the hub. (#4050)",
        cooldown_hours=12.0,
    )
except Exception:
    pass
PYEOF
    echo "[$(date -u +%FT%TZ)] === dr_drill_scheduled END status=failed (alerted) ===" >> "$LOG"
else
    echo "[$(date -u +%FT%TZ)] === dr_drill_scheduled END status=success ===" >> "$LOG"
fi

exit "$rc"
