#!/bin/bash
# ARCHIE Pre-Edit Hook — reminds agent to search KB before modifying code
# Fires on Edit and Write tool calls

cat <<'HOOK_JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "PRE-EDIT CHECK: Did you search the knowledge base (mcp search_knowledge) for this topic? Did you check for mistake_learned entries? Did you read the existing code? If not, do that FIRST — the answer may already exist. See Rule #2: Read Before Building."
  }
}
HOOK_JSON
