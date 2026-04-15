#!/bin/bash
# ARCHIE Session Init Hook — fires on SessionStart
# Injects critical context + session stats so Claude starts aware

# Get session stats
STATS=$(bash /mnt/archie_brain/.claude/hooks/session-stats.sh 2>/dev/null)

cat <<HOOK_JSON
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "SESSION INIT — MANDATORY ACTIONS:\n1. Call mcp__archie__session_briefing with the user's topic BEFORE doing any work\n2. You are on 192.168.1.200 (hub). User is REMOTE. Never use localhost.\n3. Search knowledge base before building anything new.\n4. Read .claude/rules/operational-state.md for product registry + deployment map.\n5. Consciousness loops are ENABLED — do NOT disable them (Decision #369).\n6. Architecture: Autonomy=jobs, Department HQ=agents+fleet+dispatch, AI Bridge=routing+models.\n7. 2 failures on any task → STOP and ask user. Never spiral.\n\n## Session Stats\n${STATS}\n\n## Session Awareness\n- Run /archie-stats anytime to check session metrics\n- Run /archie-save for mid-session checkpoint\n- Run /archie-compact if context feels heavy\n- Run /archie-end for full session close-out\n- User is on Max 20x plan — maximize available resources\n- Monitor your context window usage — suggest /compact proactively when heavy"
  }
}
HOOK_JSON
