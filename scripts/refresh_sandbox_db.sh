#!/usr/bin/env bash
# scripts/refresh_sandbox_db.sh
# Refreshes archie_staging_db from the latest daily production backup.
# Runs on the HOST (not inside a container) — has access to /mnt/data2/backups.
# Cron: 30 4 * * * root SANDBOX_DB_PASSWORD=$(cat /mnt/archie_brain/secrets/db_password) bash /mnt/archie_brain/scripts/refresh_sandbox_db.sh >> /var/log/archie_sandbox_refresh.log 2>&1
set -euo pipefail

BACKUP_DIR="/mnt/data2/backups"
DB_NAME="archie"
DB_USER="archie"
DB_HOST="127.0.0.1"
DB_PORT="5433"
STAGING_CONTAINER="archie_staging"
LOG_PREFIX="[sandbox-db-refresh $(date '+%Y-%m-%d %H:%M:%S EDT')]"

SANDBOX_DB_PASSWORD="${SANDBOX_DB_PASSWORD:-$(cat /mnt/archie_brain/secrets/db_password)}"

echo "$LOG_PREFIX Starting sandbox DB refresh..."

# Find the latest .dump file in any daily backup directory
LATEST=$(find "$BACKUP_DIR" -name "archie_*.dump" -path "*/daily/*" | sort | tail -1)
if [ -z "$LATEST" ]; then
    echo "$LOG_PREFIX ERROR: No .dump file found under $BACKUP_DIR/*/daily/"
    exit 1
fi
echo "$LOG_PREFIX Using backup: $LATEST"

# Check staging DB container is running
if ! docker ps --format '{{.Names}}' | grep -q "^archie_staging_db$"; then
    echo "$LOG_PREFIX ERROR: archie_staging_db container is not running. Start it first."
    exit 1
fi

# Drop and recreate the database
PGPASSWORD="$SANDBOX_DB_PASSWORD" psql \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $DB_NAME;" \
    -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
echo "$LOG_PREFIX Dropped and recreated '$DB_NAME' database."

# Restore
PGPASSWORD="$SANDBOX_DB_PASSWORD" pg_restore \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --username="$DB_USER" \
    --dbname="$DB_NAME" \
    --no-owner \
    --no-privileges \
    "$LATEST" 2>&1 | grep -v "^pg_restore: warning" || true

echo "$LOG_PREFIX pg_restore completed."

# Restart staging container to pick up fresh DB
docker restart "$STAGING_CONTAINER"
echo "$LOG_PREFIX $STAGING_CONTAINER restarted."

echo "$LOG_PREFIX Sandbox DB refresh complete."
