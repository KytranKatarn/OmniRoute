#!/bin/bash
# ==============================================================================
# A.R.C.H.I.E. Weekly Memory Decay Script
# Runs via crontab on Sunday at 4 AM
# ==============================================================================

set -e

LOG_FILE="/var/log/archie_memory.log"
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/archie_memory.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
}

log "========================================="
log "Starting weekly memory decay process"

# Run memory decay
DECAY_RESULT=$(docker exec archie_platform python3 -c "
try:
    from tools.consciousness.memory_service import apply_decay
    result = apply_decay()
    print(f'Memory decay applied successfully')
except ImportError:
    # Try alternative import path
    try:
        from consciousness.memory_service import apply_decay
        result = apply_decay()
        print(f'Memory decay applied successfully')
    except Exception as e:
        print(f'Memory decay not available: {e}')
except Exception as e:
    print(f'Error: {e}')
" 2>&1)

log "Memory decay result: $DECAY_RESULT"

# Report knowledge base stats
KB_STATS=$(docker exec archie_database psql -U archie -d archie -t -c "
SELECT COUNT(*) || ' total entries, ' ||
       COALESCE(SUM(CASE WHEN importance_score < 0.3 THEN 1 ELSE 0 END), 0) || ' low importance'
FROM knowledge_base;
" 2>&1)

log "Knowledge base stats: $KB_STATS"

log "Weekly memory decay completed"
log "========================================="

exit 0
