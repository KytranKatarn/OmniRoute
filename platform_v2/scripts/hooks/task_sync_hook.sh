#!/bin/bash
# Task Sync Hook - Syncs Claude Code tasks to A.R.C.H.I.E. Blueprint
# Triggered after task completion to maintain roadmap alignment

PLATFORM_URL="http://localhost:3000"
LOG_FILE="/mnt/archie_brain/logs/task_sync.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Get task info from environment (passed by Claude Code)
TASK_CONTENT="${CLAUDE_TASK_CONTENT:-}"
TASK_STATUS="${CLAUDE_TASK_STATUS:-}"
SESSION_ID="${CLAUDE_SESSION_ID:-$(date +%s)}"

if [ -z "$TASK_CONTENT" ]; then
    # No task info provided, try to extract from recent activity
    exit 0
fi

log "Task sync triggered: $TASK_STATUS - $TASK_CONTENT"

# Find matching phase based on task content keywords
find_phase() {
    local content="$1"

    # Query Blueprint API for phases
    PHASES=$(curl -s "$PLATFORM_URL/tools/blueprint/api/phases" 2>/dev/null)

    if [ $? -ne 0 ] || [ -z "$PHASES" ]; then
        log "Could not fetch phases from Blueprint API"
        return 1
    fi

    # Use Python to find best matching phase
    python3 << EOF
import json
import sys

try:
    phases = json.loads('''$PHASES''')
    content = '''$content'''.lower()

    # Keywords to phase mapping
    keywords = {
        'mcp': [50, 51],
        'bridge': [52, 53],
        'command': [56, 57],
        'agent': [63, 64],
        'improvement': [5, 6, 7, 8],
        'sandbox': [9, 10, 11],
        'deploy': [12, 13, 14],
        'ui': [25, 26, 27],
        'blueprint': [31],
        'goose': [55],
        'knowledge': [1, 2, 3],
        'mistake': [4],
    }

    for keyword, phase_nums in keywords.items():
        if keyword in content:
            for phase in phases.get('phases', []):
                if phase.get('phase_number') in phase_nums:
                    print(phase.get('id', ''))
                    sys.exit(0)

    # No match found
    print('')
except Exception as e:
    print('', file=sys.stderr)
EOF
}

# Sync task to Blueprint
sync_task() {
    local phase_id="$1"
    local content="$2"
    local status="$3"

    if [ -z "$phase_id" ]; then
        log "No matching phase found for task"
        return 1
    fi

    # Check if task already exists
    EXISTING=$(curl -s "$PLATFORM_URL/tools/blueprint/api/phases/$phase_id/tasks" 2>/dev/null | \
        python3 -c "import sys,json; tasks=json.load(sys.stdin).get('tasks',[]); print(next((t['id'] for t in tasks if '$content'[:50] in t.get('description','')), ''))" 2>/dev/null)

    if [ -n "$EXISTING" ]; then
        # Update existing task
        if [ "$status" = "completed" ]; then
            curl -s -X PUT "$PLATFORM_URL/tools/blueprint/api/tasks/$EXISTING" \
                -H "Content-Type: application/json" \
                -d '{"done": true}' > /dev/null 2>&1
            log "Updated task $EXISTING as completed"
        fi
    else
        # Create new task
        DONE_VALUE="false"
        [ "$status" = "completed" ] && DONE_VALUE="true"

        curl -s -X POST "$PLATFORM_URL/tools/blueprint/api/phases/$phase_id/tasks" \
            -H "Content-Type: application/json" \
            -d "{\"description\": \"[Claude] $content\", \"done\": $DONE_VALUE}" > /dev/null 2>&1
        log "Created new task in phase $phase_id"
    fi
}

# Main execution
PHASE_ID=$(find_phase "$TASK_CONTENT")
sync_task "$PHASE_ID" "$TASK_CONTENT" "$TASK_STATUS"

echo "Task synced to Blueprint"
