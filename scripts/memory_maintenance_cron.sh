#!/bin/bash
# Memory Maintenance Cron Job
# Run daily at 3 AM: 0 3 * * * /mnt/archie_brain/scripts/memory_maintenance_cron.sh
# Phase 8: Long-Term Memory Integration

LOG_FILE="/mnt/archie_brain/logs/memory_maintenance.log"
mkdir -p /mnt/archie_brain/logs

echo "=== Memory Maintenance Started: $(date -Iseconds) ===" >> "$LOG_FILE"

# Run memory maintenance via API
RESPONSE=$(curl -s -X POST http://localhost:3000/tools/consciousness/api/memory/maintenance \
    -H "Content-Type: application/json" \
    --cookie "session=admin" 2>&1)

if echo "$RESPONSE" | grep -q '"success": true' 2>/dev/null; then
    echo "SUCCESS: Memory maintenance completed" >> "$LOG_FILE"
    echo "$RESPONSE" >> "$LOG_FILE"
else
    echo "FALLBACK: Running maintenance directly via database" >> "$LOG_FILE"

    # Direct database execution as fallback
    docker exec archie_database psql -U archie -d archie -c "SELECT * FROM run_memory_maintenance();" >> "$LOG_FILE" 2>&1
fi

echo "=== Memory Maintenance Finished: $(date -Iseconds) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
