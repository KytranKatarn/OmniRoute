#!/bin/sh
# A.R.C.H.I.E. Deployment Watchdog (POSIX shell - works in alpine/docker:cli)
# Runs EXTERNALLY to monitor container health and auto-rollback if needed

CONTAINER_NAME="archie_platform"
DEPLOYMENT_INFO="/mnt/archie_brain/backups/last_deployment.json"
LOG_FILE="/mnt/archie_brain/logs/deployment_watchdog.log"
HEALTH_TIMEOUT=90
CHECK_INTERVAL=5

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE" 2>&1
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "========================================"
log "DEPLOYMENT WATCHDOG STARTED"
log "========================================"

# Check if deployment info exists
if [ ! -f "$DEPLOYMENT_INFO" ]; then
    log "No deployment info found - exiting"
    exit 0
fi

# Read deployment info using basic tools (no python needed)
BACKUP_PATH=$(grep -o '"backup_path"[[:space:]]*:[[:space:]]*"[^"]*"' "$DEPLOYMENT_INFO" | cut -d'"' -f4)
DEPLOYMENT_ID=$(grep -o '"deployment_id"[[:space:]]*:[[:space:]]*[0-9]*' "$DEPLOYMENT_INFO" | grep -o '[0-9]*$')

# Convert container path to host path
HOST_BACKUP_PATH=$(echo "$BACKUP_PATH" | sed 's|^/backups/|/mnt/archie_brain/backups/|')

log "Deployment ID: $DEPLOYMENT_ID"
log "Backup Path: $HOST_BACKUP_PATH"

# Monitor container health
# NOTE: We need to wait for health check to actually run after restart
# The container may briefly show "healthy" (cached) before health check runs
MIN_HEALTHY_TIME=20  # Require healthy for at least 20s
HEALTHY_STREAK=0     # Count consecutive healthy checks

log "Monitoring container health for ${HEALTH_TIMEOUT}s..."
log "Requiring ${MIN_HEALTHY_TIME}s of sustained healthy status..."
ELAPSED=0
HEALTHY="false"

while [ $ELAPSED -lt $HEALTH_TIMEOUT ]; do
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))

    # Check container status
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "error")
    CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "not_found")

    log "Check ${ELAPSED}s: container=$CONTAINER_STATUS, health=$HEALTH_STATUS (streak=$HEALTHY_STREAK)"

    # Check for crash loop (restarting status)
    if [ "$CONTAINER_STATUS" = "restarting" ]; then
        log "Container is in CRASH LOOP! Initiating rollback..."
        break
    fi

    # Check for explicit failure states
    if [ "$CONTAINER_STATUS" = "exited" ] || [ "$HEALTH_STATUS" = "unhealthy" ]; then
        log "Container FAILED! Initiating rollback..."
        break
    fi

    # Track healthy streak
    if [ "$HEALTH_STATUS" = "healthy" ]; then
        HEALTHY_STREAK=$((HEALTHY_STREAK + CHECK_INTERVAL))
        if [ $HEALTHY_STREAK -ge $MIN_HEALTHY_TIME ]; then
            HEALTHY="true"
            log "Sustained healthy status confirmed!"
            break
        fi
    else
        # Reset streak if not healthy (starting, etc.)
        HEALTHY_STREAK=0
    fi
done

if [ "$HEALTHY" = "true" ]; then
    log "========================================"
    log "SUCCESS: Container is healthy!"
    log "========================================"

    # Update database
    docker exec archie_database psql -U archie -d archie -c \
        "UPDATE improvement_deployments SET post_deployment_metrics = jsonb_build_object('restart_verified', true, 'watchdog', 'external') WHERE id = $DEPLOYMENT_ID;" 2>/dev/null

    rm -f "$DEPLOYMENT_INFO"
    exit 0
fi

# ========================================
# ROLLBACK PROCEDURE
# ========================================
log "========================================"
log "INITIATING AUTOMATIC ROLLBACK"
log "========================================"

# Stop the failed container
log "Stopping failed container..."
docker stop "$CONTAINER_NAME" 2>/dev/null

# Restore files from backup
# Use modified_files from deployment info to find correct paths
if [ -d "$HOST_BACKUP_PATH" ]; then
    log "Restoring from: $HOST_BACKUP_PATH"

    # Read modified_files array from JSON (handles multiline arrays)
    MODIFIED_FILES=$(cat "$DEPLOYMENT_INFO" | tr -d '\n' | \
                     sed 's/.*"modified_files"[[:space:]]*:[[:space:]]*\[//' | \
                     sed 's/\].*//' | \
                     tr -d '"' | \
                     tr ',' '\n' | \
                     tr -d ' ' | \
                     grep -v '^$')

    for mod_file in $MODIFIED_FILES; do
        # Get just the filename
        filename=$(basename "$mod_file")
        backup_file="$HOST_BACKUP_PATH/${filename}.backup"

        if [ -f "$backup_file" ]; then
            # Convert relative path to absolute host path
            # Handle platform_v2/ and ai_bridge/ prefixes
            if echo "$mod_file" | grep -q "^platform_v2/"; then
                # Strip platform_v2/ and prepend /mnt/archie_brain/platform_v2/
                rel_path=$(echo "$mod_file" | sed 's|^platform_v2/||')
                target_file="/mnt/archie_brain/platform_v2/$rel_path"
            elif echo "$mod_file" | grep -q "^ai_bridge/"; then
                # Strip ai_bridge/ and prepend /mnt/archie_brain/ai_bridge/
                rel_path=$(echo "$mod_file" | sed 's|^ai_bridge/||')
                target_file="/mnt/archie_brain/ai_bridge/$rel_path"
            else
                # Assume it's relative to platform_v2
                target_file="/mnt/archie_brain/platform_v2/$mod_file"
            fi

            log "Restoring: $backup_file -> $target_file"
            cp "$backup_file" "$target_file" 2>/dev/null

            if [ $? -eq 0 ]; then
                log "  SUCCESS"
            else
                log "  FAILED - trying find fallback..."
                # Fallback to find if direct path fails
                fallback=$(find /mnt/archie_brain -name "$filename" -type f -path "*tools/improvements*" 2>/dev/null | head -1)
                if [ -n "$fallback" ]; then
                    cp "$backup_file" "$fallback"
                    log "  Fallback restored to: $fallback"
                fi
            fi
        else
            log "WARNING: No backup found for $filename"
        fi
    done

    log "Files restored"
else
    log "ERROR: Backup not found: $HOST_BACKUP_PATH"
fi

# Restart with restored files
log "Starting container with restored code..."
docker start "$CONTAINER_NAME"

sleep 15

# Update database
docker exec archie_database psql -U archie -d archie -c \
    "UPDATE improvement_deployments SET status = 'rolled_back', rolled_back_at = NOW(), rollback_reason = 'Auto-rollback by external watchdog' WHERE id = $DEPLOYMENT_ID;
     UPDATE improvement_proposals SET status = 'failed' WHERE id = (SELECT proposal_id FROM improvement_deployments WHERE id = $DEPLOYMENT_ID);" 2>/dev/null

rm -f "$DEPLOYMENT_INFO"

log "========================================"
log "ROLLBACK COMPLETE"
log "========================================"

exit 1
