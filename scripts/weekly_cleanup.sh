#!/bin/bash
# ==============================================================================
# A.R.C.H.I.E. Weekly Cleanup Script
# Runs via crontab on Sunday at 3 AM
# ==============================================================================

set -e

LOG_FILE="/var/log/archie_backup.log"
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/archie_backup.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
}

log "========================================="
log "Starting weekly A.R.C.H.I.E. cleanup"

# Run backup cleanup (uses GFS retention policy)
log "Running backup cleanup..."
CLEANUP_RESULT=$(docker exec archie_platform python3 -c "
from tools.backup_manager.backup_manager_routes import cleanup_old_backups
result = cleanup_old_backups(dry_run=False)
print(f\"Cleanup complete - Deleted: {result.get('deleted_count', 0)} backups\")
" 2>&1)

log "Cleanup result: $CLEANUP_RESULT"

# Report disk usage
BACKUP_SIZE=$(du -sh /mnt/archie_brain/backups/ 2>/dev/null | cut -f1)
log "Backup storage after cleanup: $BACKUP_SIZE"

log "Weekly cleanup completed"
log "========================================="

exit 0
