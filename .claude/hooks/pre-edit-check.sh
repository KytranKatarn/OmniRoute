#!/bin/bash
# ARCHIE Pre-Edit Hook — injects ACTUAL context before any file edit
# Fires on Edit and Write tool calls

# Parse file path from tool input stdin
FILE_PATH=$(cat /dev/stdin 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('file_path', d.get('path', 'unknown')))
except:
    print('unknown')
" 2>/dev/null || echo "unknown")

# Recent git commits for this file
GIT_LOG=""
if [ "$FILE_PATH" != "unknown" ] && [ -f "$FILE_PATH" ]; then
    GIT_LOG=$(cd /mnt/archie_brain && git log --oneline -5 -- "$FILE_PATH" 2>/dev/null)
fi

# Find module name from path and load rules
MODULE=$(echo "$FILE_PATH" | sed 's|.*/tools/||;s|/.*||;s|\.py$||' 2>/dev/null)
RULES=""
RULES_FILE="/mnt/archie_brain/.claude/rules/${MODULE}.md"
if [ -f "$RULES_FILE" ]; then
    RULES=$(head -40 "$RULES_FILE" 2>/dev/null)
fi

# Current fire from handoff (top 8 lines of first session entry)
HANDOFF=$(head -25 /home/kytran/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md 2>/dev/null | grep -A8 "Status:" | head -8)

CONTEXT="PRE-EDIT RECALL — ${FILE_PATH}

RECENT COMMITS FOR THIS FILE:
${GIT_LOG:-none}

MODULE RULES (${MODULE}):
${RULES:-no rules file found — check .claude/rules/}

CURRENT FIRE (from handoff):
${HANDOFF:-read project_session-handoff.md}

REQUIRED: Before editing, state in your response:
1. What you are changing and exactly why
2. What the last known state of this code was
3. What could break downstream"

# Escape for JSON
CONTEXT_JSON=$(echo "$CONTEXT" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" 2>/dev/null)

cat <<HOOK_JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": ${CONTEXT_JSON}
  }
}
HOOK_JSON
