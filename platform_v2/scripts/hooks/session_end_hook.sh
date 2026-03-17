#!/bin/bash
# Session End Hook - Triggered when Claude Code session ends
# Phase 7: Full session capture with database storage

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SESSION_NAME=$(basename "$PWD")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
LOG_DIR="/mnt/archie_brain/conversation_logs"
PLATFORM_DIR="/mnt/archie_brain/platform_v2"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# ============================================================================
# SESSION END DISPLAY
# ============================================================================
echo ""
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                       ║"
echo "║    💾💾💾  A.R.C.H.I.E. SESSION END - SAVING FINAL STATE  💾💾💾       ║"
echo "║                                                                       ║"
echo "╠═══════════════════════════════════════════════════════════════════════╣"
echo "║                                                                       ║"
echo "║    📝 Saving session summary to consciousness...                    ║"
echo "║                                                                       ║"

# Get git stats for this session
GIT_COMMITS_TODAY=$(git log --oneline --since="4 hours ago" 2>/dev/null | wc -l)
GIT_FILES_CHANGED=$(git diff --name-only HEAD~${GIT_COMMITS_TODAY:-1} 2>/dev/null | wc -l)

echo "║    Session Summary:                                                   ║"
echo "║    ├── Branch: $GIT_BRANCH"
echo "║    ├── Commits this session: ${GIT_COMMITS_TODAY:-0}"
echo "║    └── Files touched: ${GIT_FILES_CHANGED:-0}"
echo "║                                                                       ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# LOG TO LOCAL FILE
# ============================================================================
cat >> "$LOG_DIR/session_history.log" <<EOF
[$(date -Iseconds)] SESSION END
  Session: $SESSION_NAME
  Git Branch: $GIT_BRANCH
  Git Commit: $GIT_COMMIT
  Working Directory: $PWD
  Commits: ${GIT_COMMITS_TODAY:-0}
  Files Changed: ${GIT_FILES_CHANGED:-0}
---
EOF

# Create session end metadata JSON
cat > "$LOG_DIR/session_end_${TIMESTAMP}.json" <<EOF
{
  "event": "session_end",
  "timestamp": "$(date -Iseconds)",
  "session_name": "$SESSION_NAME",
  "git_branch": "$GIT_BRANCH",
  "git_commit": "$GIT_COMMIT",
  "working_directory": "$PWD",
  "commits_this_session": ${GIT_COMMITS_TODAY:-0},
  "files_changed": ${GIT_FILES_CHANGED:-0}
}
EOF

# ============================================================================
# CAPTURE CONVERSATION (if not already captured by pre-compact)
# ============================================================================
echo "📸 Capturing final conversation state..."

python3 "$PLATFORM_DIR/scripts/capture_conversation.py" > /dev/null 2>&1

LATEST_TRANSCRIPT=$(ls -t "$LOG_DIR"/transcript_*.md 2>/dev/null | head -1)
if [ -n "$LATEST_TRANSCRIPT" ]; then
    MESSAGE_COUNT=$(grep -c "^## Message" "$LATEST_TRANSCRIPT" 2>/dev/null || echo "0")
    echo "✅ Conversation captured: $MESSAGE_COUNT messages"
else
    MESSAGE_COUNT=0
    echo "⚠️ No conversation transcript found"
fi

# ============================================================================
# SAVE TO DATABASE
# ============================================================================
echo "💾 Saving to consciousness..."

# Read transcript content (limit to last 50000 chars)
if [ -n "$LATEST_TRANSCRIPT" ] && [ -f "$LATEST_TRANSCRIPT" ]; then
    TRANSCRIPT_CONTENT=$(tail -c 50000 "$LATEST_TRANSCRIPT" | base64 -w0)
else
    TRANSCRIPT_CONTENT=""
fi

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

    # Create session end memory entry
    title = f'Session End: {session_name} ({git_branch}) - {timestamp[:10]}'

    content = f'''## Session End Summary

**Timestamp:** {timestamp}
**Branch:** {git_branch}
**Commit:** {git_commit}
**Working Directory:** {working_dir}
**Messages in Session:** {message_count}

### Git Activity
- Commits: {commits_count}
- Files Changed: {files_changed}

---

### Final Conversation State (Last 50KB)

{transcript_text if transcript_text else 'No transcript captured'}
'''

    git_metadata = {
        'branch': git_branch,
        'commit': git_commit,
        'commits_this_session': commits_count,
        'files_changed': files_changed,
        'message_count': message_count,
        'event_type': 'session_end',
        'session_end_timestamp': timestamp
    }

    # Insert into knowledge_base
    cur.execute('''
        INSERT INTO knowledge_base
        (title, content, knowledge_type, category, tags, importance_score, source_type, source_id, memory_metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (
        title,
        content,
        'conversation_memory',
        'Conversations/Sessions',
        ['session-end', 'conversation', git_branch, 'claude-code', 'session-' + timestamp[:10]],
        0.75,  # Slightly lower than compact checkpoints
        'claude_code_hook',
        'session-end-' + timestamp[:19].replace(':', '-'),
        Json(git_metadata)
    ))

    entry_id = cur.fetchone()[0]
    conn.commit()
    print(f'Saved session end to knowledge_base (ID: {entry_id})')

    # Also insert/update conversation_sessions
    cur = conn.cursor()

    # Check if there's a recent session to update (within last 4 hours)
    cur.execute('''
        SELECT id FROM conversation_sessions
        WHERE session_name = %s AND git_branch = %s
        AND compact_triggered_at > NOW() - INTERVAL '4 hours'
        ORDER BY compact_triggered_at DESC LIMIT 1
    ''', (session_name, git_branch))

    existing = cur.fetchone()

    if existing:
        # Update existing session with end time
        cur.execute('''
            UPDATE conversation_sessions
            SET ended_at = NOW(),
                duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::int,
                processing_status = 'completed',
                updated_at = NOW()
            WHERE id = %s
        ''', (existing[0],))
        print(f'Updated conversation_sessions (ID: {existing[0]}) with end time')
    else:
        # Create new session entry
        cur.execute('''
            INSERT INTO conversation_sessions
            (session_name, git_branch, git_commit, working_directory,
             started_at, ended_at, compact_triggered_at, full_transcript,
             primary_topic, phase, tags, knowledge_entries_created,
             processing_status, metadata)
            VALUES (%s, %s, %s, %s, NOW() - INTERVAL '2 hours', NOW(), NOW(), %s,
                    'development', 'active', %s, %s, 'completed', %s)
            RETURNING id
        ''', (
            session_name,
            git_branch,
            git_commit,
            working_dir,
            transcript_text if transcript_text else 'No transcript captured',
            ['session-end', 'claude-code', git_branch],
            [entry_id],
            Json(git_metadata)
        ))
        session_id = cur.fetchone()[0]
        print(f'Created conversation_sessions (ID: {session_id})')

    conn.commit()
    cur.close()
    conn.close()

except Exception as e:
    print(f'Error saving to database: {e}')
" >> "$LOG_DIR/capture.log" 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Session saved to consciousness"
else
    echo "⚠️ Database save failed"
    echo "   Check $LOG_DIR/capture.log for details"
fi

echo ""
echo "👋 Session complete - goodbye!"
