#!/usr/bin/env bash
# scripts/refresh_sandbox_db.sh
# Refreshes archie_staging_db from the latest daily production backup.
# Runs psql/pg_restore INSIDE the archie_staging_db container (host lacks Postgres tools).
# Cron: 30 4 * * * bash /mnt/archie_brain/scripts/refresh_sandbox_db.sh >> /var/log/archie_sandbox_refresh.log 2>&1
set -euo pipefail

BACKUP_DIR="/mnt/data2/backups"
DB_NAME="archie"
DB_USER="archie"
DB_CONTAINER="archie_staging_db"
STAGING_CONTAINER="archie_staging"
LOG_PREFIX="[sandbox-db-refresh $(date '+%Y-%m-%d %H:%M:%S EDT')]"

echo "$LOG_PREFIX Starting sandbox DB refresh..."

# Find the latest .dump file in any daily backup directory (suppress permission errors)
LATEST=$(find "$BACKUP_DIR" -name "archie_*.dump" -path "*/daily/*" 2>/dev/null | sort | tail -1)
if [ -z "$LATEST" ]; then
    echo "$LOG_PREFIX ERROR: No .dump file found under $BACKUP_DIR/*/daily/"
    exit 1
fi
echo "$LOG_PREFIX Using backup: $LATEST"

# Check staging DB container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
    echo "$LOG_PREFIX ERROR: $DB_CONTAINER container is not running. Start it first."
    exit 1
fi

# Drop and recreate the database (run inside the container — no host psql needed)
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $DB_NAME;" \
    -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
echo "$LOG_PREFIX Dropped and recreated '$DB_NAME' database."

# Restore (run inside the container — dump is mounted at /mnt/data2 via compose volume)
docker exec "$DB_CONTAINER" pg_restore \
    --host=localhost \
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
