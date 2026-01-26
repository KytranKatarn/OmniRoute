#!/bin/bash
# A.R.C.H.I.E. Safe Restart with Auto-Rollback
# This script monitors container health after restart and rolls back if needed

set -e

CONTAINER_NAME="archie_platform"
HEALTH_TIMEOUT=60  # seconds to wait for healthy status
CHECK_INTERVAL=5   # seconds between health checks
DEPLOYMENT_INFO_FILE="/mnt/archie_brain/backups/last_deployment.json"
LOG_FILE="/mnt/archie_brain/logs/safe_restart.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Read deployment info
if [ ! -f "$DEPLOYMENT_INFO_FILE" ]; then
    log "ERROR: No deployment info file found at $DEPLOYMENT_INFO_FILE"
    exit 1
fi

BACKUP_PATH=$(cat "$DEPLOYMENT_INFO_FILE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('backup_path',''))")
DEPLOYMENT_ID=$(cat "$DEPLOYMENT_INFO_FILE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('deployment_id',''))")
MODIFIED_FILES=$(cat "$DEPLOYMENT_INFO_FILE" | python3 -c "import sys,json; print(' '.join(json.load(sys.stdin).get('modified_files',[])))")

log "=========================================="
log "Safe Restart initiated"
log "Deployment ID: $DEPLOYMENT_ID"
log "Backup Path: $BACKUP_PATH"
log "Modified Files: $MODIFIED_FILES"
log "=========================================="

# Restart the container
log "Restarting container: $CONTAINER_NAME"
docker restart "$CONTAINER_NAME"

# Wait for container to be healthy
log "Waiting for container to become healthy (timeout: ${HEALTH_TIMEOUT}s)..."
ELAPSED=0
HEALTHY=false

while [ $ELAPSED -lt $HEALTH_TIMEOUT ]; do
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))

    # Check container status
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "error")

    log "Health check at ${ELAPSED}s: $STATUS"

    if [ "$STATUS" = "healthy" ]; then
        HEALTHY=true
        break
    elif [ "$STATUS" = "unhealthy" ] || [ "$STATUS" = "error" ]; then
        log "Container is $STATUS - will attempt rollback"
        break
    fi
    # "starting" status continues the loop
done

if [ "$HEALTHY" = true ]; then
    log "SUCCESS: Container is healthy after restart"

    # Update database to confirm successful restart
    docker exec archie_database psql -U archie -d archie -c "
        UPDATE improvement_deployments
        SET status = 'deployed',
            post_deployment_metrics = jsonb_build_object('restart_verified', true, 'verified_at', now()::text)
        WHERE id = $DEPLOYMENT_ID;
    " 2>/dev/null || true

    log "Deployment $DEPLOYMENT_ID verified successfully"
    exit 0
fi

# ROLLBACK PROCEDURE
log "=========================================="
log "INITIATING ROLLBACK - Container failed to start healthy"
log "=========================================="

# Stop the container first
log "Stopping container..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true

# Restore files from backup
if [ -d "$BACKUP_PATH" ]; then
    log "Restoring files from backup: $BACKUP_PATH"

    for backup_file in "$BACKUP_PATH"/*.backup; do
        if [ -f "$backup_file" ]; then
            # Get original filename (remove .backup extension)
            filename=$(basename "$backup_file" .backup)

            # Find the original file location from modified_files
            # This is simplified - in practice we'd need the full path mapping
            log "Restoring: $filename"

            # Copy backup back to /app inside container volume
            # The volume is mounted at ./platform_v2:/app
            original_path="/mnt/archie_brain/platform_v2"

            # Find where this file should go
            find "$original_path" -name "$filename" -type f | while read original_file; do
                log "  Copying $backup_file -> $original_file"
                cp "$backup_file" "$original_file"
            done
        fi
    done

    log "Files restored from backup"
else
    log "ERROR: Backup directory not found: $BACKUP_PATH"
fi

# Restart container with restored files
log "Restarting container with restored files..."
docker start "$CONTAINER_NAME"

# Wait for healthy status after rollback
ELAPSED=0
ROLLBACK_HEALTHY=false

while [ $ELAPSED -lt $HEALTH_TIMEOUT ]; do
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))

    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "error")
    log "Rollback health check at ${ELAPSED}s: $STATUS"

    if [ "$STATUS" = "healthy" ]; then
        ROLLBACK_HEALTHY=true
        break
    fi
done

# Update database with rollback status
if [ "$ROLLBACK_HEALTHY" = true ]; then
    log "ROLLBACK SUCCESS: Container is healthy after restoring backup"

    docker exec archie_database psql -U archie -d archie -c "
        UPDATE improvement_deployments
        SET status = 'rolled_back',
            rolled_back_at = NOW(),
            rollback_reason = 'Auto-rollback: Container failed health check after restart'
        WHERE id = $DEPLOYMENT_ID;

        UPDATE improvement_proposals
        SET status = 'failed',
            notes = COALESCE(notes, '') || E'\n[AUTO-ROLLBACK] Deployment caused container to fail. Restored from backup.'
        WHERE id = (SELECT proposal_id FROM improvement_deployments WHERE id = $DEPLOYMENT_ID);
    " 2>/dev/null || true

    log "Database updated with rollback status"
else
    log "CRITICAL: Rollback also failed! Manual intervention required."
fi

log "=========================================="
log "Safe Restart completed with ROLLBACK"
log "=========================================="

exit 1
