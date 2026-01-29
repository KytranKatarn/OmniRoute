#!/bin/bash
# ==============================================================================
# A.R.C.H.I.E. Daily Backup Script
# Runs via crontab at 2 AM daily
# ==============================================================================

set -e

LOG_FILE="/var/log/archie_backup.log"
EMAIL="admin@localhost"  # Configure actual email if needed
BACKUP_RETENTION_DAYS=30

# Ensure log file exists
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/archie_backup.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
}

log "========================================="
log "Starting daily A.R.C.H.I.E. backup"

# Run backup inside Docker container
RESULT=$(docker exec archie_platform python3 -c "
import json
from tools.backup_manager.backup_manager_routes import create_backup_programmatic
result = create_backup_programmatic('Daily_Scheduled', 'cron')
print('SUCCESS' if result.get('success') else 'FAILED: ' + str(result.get('error')))
" 2>&1)

log "Backup result: $RESULT"

# Check result and handle failure
if [[ "$RESULT" != *"SUCCESS"* ]]; then
    log "ERROR: Backup failed!"

    # Send email notification if mail is configured
    if command -v mail &> /dev/null; then
        echo "A.R.C.H.I.E. daily backup failed at $(date)

Result: $RESULT

Check logs at: $LOG_FILE
" | mail -s "⚠️ ARCHIE Backup FAILED" "$EMAIL" 2>/dev/null || true
    fi

    exit 1
fi

# Log disk usage
BACKUP_SIZE=$(du -sh /mnt/archie_brain/backups/ 2>/dev/null | cut -f1)
log "Total backup storage used: $BACKUP_SIZE"

# Count backups
BACKUP_COUNT=$(ls -1d /mnt/archie_brain/backups/*/ 2>/dev/null | wc -l)
log "Total backups: $BACKUP_COUNT"

log "Daily backup completed successfully"
log "========================================="

exit 0
