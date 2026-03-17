#!/bin/bash
# PreCompact Hook - Triggered when conversation context reaches ~80% (auto-compact)
# Phase 7: Full Conversation Capture with Database Storage

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SESSION_NAME=$(basename "$PWD")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "no-commit")
LOG_DIR="/mnt/archie_brain/conversation_logs"
PLATFORM_DIR="/mnt/archie_brain/platform_v2"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# ============================================================================
# MEMORY CHECKPOINT DISPLAY - PROMINENT WARNING
# ============================================================================
echo ""
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                       ║"
echo "║    🧠🧠🧠  A.R.C.H.I.E. MEMORY CHECKPOINT - SAVING CONVERSATION  🧠🧠🧠    ║"
echo "║                                                                       ║"
echo "╠═══════════════════════════════════════════════════════════════════════╣"
echo "║                                                                       ║"
echo "║    ⚠️  Context is at ~80% capacity - COMPACTING conversation         ║"
echo "║                                                                       ║"
echo "║    📝 Saving full conversation transcript to knowledge base...       ║"
echo "║                                                                       ║"

# Get git stats for this session (commits in last hour as proxy)
GIT_COMMITS_TODAY=$(git log --oneline --since="1 hour ago" 2>/dev/null | wc -l)
GIT_FILES_CHANGED=$(git diff --name-only HEAD~${GIT_COMMITS_TODAY:-1} 2>/dev/null | wc -l)
GIT_LINES_ADDED=$(git diff --stat HEAD~${GIT_COMMITS_TODAY:-1} 2>/dev/null | tail -1 | grep -oP '\d+(?= insertion)' || echo "0")
GIT_LINES_REMOVED=$(git diff --stat HEAD~${GIT_COMMITS_TODAY:-1} 2>/dev/null | tail -1 | grep -oP '\d+(?= deletion)' || echo "0")

echo "║    Session Summary:                                                     ║"
echo "║    ├── Branch: $GIT_BRANCH"
echo "║    ├── Commits this session: ${GIT_COMMITS_TODAY:-0}"
echo "║    ├── Files changed: ${GIT_FILES_CHANGED:-0}"
echo "║    └── Lines: +${GIT_LINES_ADDED:-0} / -${GIT_LINES_REMOVED:-0}"
echo "║                                                                       ║"
echo "║    💾 Saving: conversation, code changes, insights, mistakes         ║"
echo "║                                                                       ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# COLLECT GIT TIME-DIMENSION DATA
# ============================================================================

# Get recent commits during this session
GIT_RECENT_COMMITS=$(git log --oneline --since="2 hours ago" --format='{"hash":"%h","message":"%s","timestamp":"%aI"}' 2>/dev/null | head -10 | paste -sd "," -)
if [ -z "$GIT_RECENT_COMMITS" ]; then
    GIT_RECENT_COMMITS="[]"
else
    GIT_RECENT_COMMITS="[$GIT_RECENT_COMMITS]"
fi

# Get list of modified files
GIT_MODIFIED_FILES=$(git diff --name-only HEAD~5 2>/dev/null | head -20 | paste -sd '","' - | sed 's/^/["/' | sed 's/$/"]/')
if [ "$GIT_MODIFIED_FILES" = '[""]' ]; then
    GIT_MODIFIED_FILES="[]"
fi

# Log the compact event with enhanced metadata
cat >> "$LOG_DIR/compact_events.log" <<EOF
[$(date -Iseconds)] AUTO-COMPACT TRIGGERED
  Session: $SESSION_NAME
  Git Branch: $GIT_BRANCH
  Git Commit: $GIT_COMMIT
  Working Directory: $PWD
  Context: ~80% full (auto-compacting)
  Commits This Session: ${GIT_COMMITS_TODAY:-0}
  Files Changed: ${GIT_FILES_CHANGED:-0}
  Lines: +${GIT_LINES_ADDED:-0} / -${GIT_LINES_REMOVED:-0}
---
EOF

# Create session snapshot with git time-dimension
cat > "$LOG_DIR/snapshot_${TIMESTAMP}.json" <<EOF
{
  "timestamp": "$(date -Iseconds)",
  "session_name": "$SESSION_NAME",
  "git_branch": "$GIT_BRANCH",
  "git_commit": "$GIT_COMMIT",
  "working_directory": "$PWD",
  "compact_type": "auto",
  "context_usage": "~80%",
  "git_timeline": {
    "branch": "$GIT_BRANCH",
    "current_commit": "$GIT_COMMIT",
    "commits_this_session": ${GIT_COMMITS_TODAY:-0},
    "files_changed": ${GIT_FILES_CHANGED:-0},
    "lines_added": ${GIT_LINES_ADDED:-0},
    "lines_removed": ${GIT_LINES_REMOVED:-0},
    "modified_files": $GIT_MODIFIED_FILES,
    "recent_commits": $GIT_RECENT_COMMITS
  },
  "session_timeline": {
    "compact_triggered": "$(date -Iseconds)"
  }
}
EOF

# ============================================================================
# STEP 1: CAPTURE FULL CONVERSATION FROM CLAUDE HISTORY
# ============================================================================
echo "📸 Capturing conversation from Claude history..."

# Run capture_conversation.py to extract conversation
TRANSCRIPT_FILE="$LOG_DIR/transcript_${TIMESTAMP}.md"
python3 "$PLATFORM_DIR/scripts/capture_conversation.py" > /dev/null 2>&1

# Find the most recent transcript file
LATEST_TRANSCRIPT=$(ls -t "$LOG_DIR"/transcript_*.md 2>/dev/null | head -1)
if [ -n "$LATEST_TRANSCRIPT" ]; then
    echo "✅ Conversation captured: $LATEST_TRANSCRIPT"
    MESSAGE_COUNT=$(grep -c "^## Message" "$LATEST_TRANSCRIPT" 2>/dev/null || echo "0")
    echo "   Messages: $MESSAGE_COUNT"
else
    echo "⚠️ No conversation transcript found"
    LATEST_TRANSCRIPT=""
    MESSAGE_COUNT=0
fi

# ============================================================================
# STEP 2: SAVE FULL CONVERSATION TO DATABASE
# ============================================================================
echo "💾 Saving to knowledge base..."

# Read transcript content (limit to last 50000 chars to avoid huge entries)
if [ -n "$LATEST_TRANSCRIPT" ] && [ -f "$LATEST_TRANSCRIPT" ]; then
    TRANSCRIPT_CONTENT=$(tail -c 50000 "$LATEST_TRANSCRIPT" | base64 -w0)
else
    TRANSCRIPT_CONTENT=""
fi

# Save to database using Docker exec (runs inside container with DB access)
docker exec archie_platform python3 -c "
import psycopg2
from psycopg2.extras import Json
import os
import base64
from datetime import datetime

# Session metadata
timestamp = '$(date -Iseconds)'
session_name = '$SESSION_NAME'
git_branch = '$GIT_BRANCH'
git_commit = '$GIT_COMMIT'
working_dir = '$PWD'
commits_count = ${GIT_COMMITS_TODAY:-0}
files_changed = ${GIT_FILES_CHANGED:-0}
lines_added = ${GIT_LINES_ADDED:-0}
lines_removed = ${GIT_LINES_REMOVED:-0}
message_count = $MESSAGE_COUNT
transcript_b64 = '$TRANSCRIPT_CONTENT'

try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD')
    )
    cur = conn.cursor()

    # Decode transcript if available
    transcript_text = ''
    if transcript_b64:
        try:
            transcript_text = base64.b64decode(transcript_b64).decode('utf-8', errors='replace')
        except:
            transcript_text = 'Failed to decode transcript'

    # Create comprehensive session memory entry
    title = f'Conversation Checkpoint: {session_name} ({git_branch}) - {timestamp[:10]}'

    content = f'''## Auto-Compact Conversation Checkpoint

**Timestamp:** {timestamp}
**Branch:** {git_branch}
**Commit:** {git_commit}
**Working Directory:** {working_dir}
**Messages Captured:** {message_count}

### Git Activity This Session
- Commits: {commits_count}
- Files Changed: {files_changed}
- Lines: +{lines_added} / -{lines_removed}

---

### Conversation Transcript (Last 50KB)

{transcript_text if transcript_text else 'No transcript captured'}
'''

    git_metadata = {
        'branch': git_branch,
        'commit': git_commit,
        'commits_this_session': commits_count,
        'files_changed': files_changed,
        'lines_added': lines_added,
        'lines_removed': lines_removed,
        'message_count': message_count,
        'compact_timestamp': timestamp
    }

    cur.execute('''
        INSERT INTO knowledge_base
        (title, content, knowledge_type, category, tags, importance_score, source_type, source_id, memory_metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (
        title,
        content,
        'conversation_memory',
        'Conversations/Checkpoints',
        ['auto-compact', 'conversation', git_branch, 'claude-code', 'session-' + timestamp[:10]],
        0.85,  # Higher importance for full conversation captures
        'claude_code_hook',
        'auto-compact-' + timestamp[:19].replace(':', '-'),
        Json(git_metadata)
    ))

    entry_id = cur.fetchone()[0]
    conn.commit()
    print(f'Saved conversation checkpoint to knowledge_base (ID: {entry_id})')

    # STEP 3: Also insert into conversation_sessions for consciousness tracking
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO conversation_sessions
        (session_name, git_branch, git_commit, working_directory,
         started_at, compact_triggered_at, full_transcript,
         primary_topic, phase, tags, knowledge_entries_created,
         processing_status, metadata)
        VALUES (%s, %s, %s, %s, NOW() - INTERVAL '2 hours', NOW(), %s,
                'development', 'active', %s, %s, 'raw', %s)
        RETURNING id
    ''', (
        session_name,
        git_branch,
        git_commit,
        working_dir,
        transcript_text if transcript_text else 'No transcript captured',
        ['auto-compact', 'claude-code', git_branch],
        [entry_id],
        Json(git_metadata)
    ))

    session_id = cur.fetchone()[0]
    conn.commit()
    print(f'Saved to conversation_sessions (ID: {session_id})')

    cur.close()
    conn.close()

except Exception as e:
    print(f'Error saving to database: {e}')
" >> "$LOG_DIR/capture.log" 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Full conversation saved to knowledge_base AND conversation_sessions"

    # ============================================================================
    # STEP 4: TRIGGER TRIAGE PIPELINE (Phase 42)
    # ============================================================================
    echo "🔬 Triggering triage pipeline for knowledge extraction..."

    # Call triage batch endpoint to process recent conversations
    TRIAGE_RESPONSE=$(curl -s -X POST http://localhost:3000/api/triage/batch \
        -H "Content-Type: application/json" \
        -d '{"limit": 1}' 2>/dev/null)

    if echo "$TRIAGE_RESPONSE" | grep -q '"success": true' 2>/dev/null; then
        EXTRACTED=$(echo "$TRIAGE_RESPONSE" | grep -oP '"extractions":\s*\d+' | grep -oP '\d+' || echo "0")
        echo "✅ Triage complete: Extracted knowledge from conversation"
        echo "   (Errors, code snippets, insights → Knowledge base)"
    else
        echo "⚠️ Triage API not available (will process later)"
        # Queue for later processing - the conversation is already saved
    fi
else
    echo "⚠️ Database save failed (compaction will proceed)"
    echo "   Check $LOG_DIR/capture.log for details"
fi

# ============================================================================
# STEP 5: EXTRACT KEY INSIGHTS (Phase 64: Claude Code Optimization)
# ============================================================================
echo "🔍 Extracting key insights from conversation..."

if [ -n "$LATEST_TRANSCRIPT" ] && [ -f "$LATEST_TRANSCRIPT" ]; then
    # Run insights extractor
    INSIGHTS_RESULT=$(docker exec archie_platform python3 \
        /mnt/archie_brain/platform_v2/conversation_insights_extractor.py \
        "$LATEST_TRANSCRIPT" 2>&1)

    if echo "$INSIGHTS_RESULT" | grep -q '"success": true' 2>/dev/null; then
        DECISIONS=$(echo "$INSIGHTS_RESULT" | grep -oP '"decisions":\s*\d+' | grep -oP '\d+' || echo "0")
        LEARNINGS=$(echo "$INSIGHTS_RESULT" | grep -oP '"learnings":\s*\d+' | grep -oP '\d+' || echo "0")
        ERRORS=$(echo "$INSIGHTS_RESULT" | grep -oP '"errors":\s*\d+' | grep -oP '\d+' || echo "0")
        TODOS=$(echo "$INSIGHTS_RESULT" | grep -oP '"todos":\s*\d+' | grep -oP '\d+' || echo "0")
        STORED=$(echo "$INSIGHTS_RESULT" | grep -oP '"stored":\s*\d+' | grep -oP '\d+' || echo "0")

        echo "✅ Insights extracted and stored:"
        echo "   Decisions: $DECISIONS | Learnings: $LEARNINGS | Errors: $ERRORS | TODOs: $TODOS"
        echo "   Total stored to knowledge base: $STORED entries"
    else
        echo "⚠️ Insights extraction completed (check logs for details)"
    fi
else
    echo "⚠️ No transcript available for insight extraction"
fi

echo ""
echo "🧠 Memory checkpoint complete - compaction proceeding..."
