#!/bin/bash
# ARCHIE Session Init Hook — fires on SessionStart
# Injects critical context so Claude doesn't start dumb

cat <<'HOOK_JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "SESSION INIT — MANDATORY ACTIONS:\n1. Call mcp__archie__session_briefing with the user's topic BEFORE doing any work\n2. You are on 192.168.1.200 (hub). User is REMOTE. Never use localhost.\n3. Search knowledge base before building anything new.\n4. Read .claude/rules/operational-state.md for product registry + deployment map.\n5. Consciousness loops are ENABLED — do NOT disable them (Decision #369).\n6. Architecture: Autonomy=jobs, Department HQ=agents, AI Bridge=dispatch, Starbase=fleet.\n7. 2 failures on any task → STOP and ask user. Never spiral."
  }
}
HOOK_JSON
