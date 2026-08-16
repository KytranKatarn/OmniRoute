#!/bin/bash
# ARCHIE Session Init Hook — injects REAL state at boot, not instructions
# Fires on SessionStart

STATS=$(bash /mnt/archie_brain/.claude/hooks/session-stats.sh 2>/dev/null)

# Real handoff — top session entry (what's broken RIGHT NOW)
HANDOFF=$(head -60 /home/kytran/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md 2>/dev/null | sed -n '/^## Session/,/^---/p' | head -40)

# Git state — what files are in play
GIT_BRANCH=$(cd /mnt/archie_brain && git branch --show-current 2>/dev/null)
GIT_STATUS=$(cd /mnt/archie_brain && git status --short 2>/dev/null | head -15)

# Owner identity (canonical — never ask again)
OWNER="Owner: Kytran Katarn | Canonical login: kytran@kytranempowerment.com (email+password, username 'kytran', users.id=4) — Google SSO REMOVED 2026-05-06 | kytranempowerment@gmail.com = BACKUP Google account, used to Google-sign-in to EXTERNAL sites (incl. LinkedIn profile 342) — NOT the platform login | admin@KytranEmpowerment.com = Claude/ARCHIE agent account only, NOT Kytran's identity | Hub: 192.168.1.200 | User is REMOTE"

CONTEXT="SESSION INIT — REAL STATE

## OWNER IDENTITY (read once, never forget)
${OWNER}

## CURRENT BRANCH + MODIFIED FILES
Branch: ${GIT_BRANCH}
${GIT_STATUS}

## WHAT IS BROKEN RIGHT NOW (from handoff)
${HANDOFF}

## HARD RULES
- 2 failures → STOP, ask user. Never spiral.
- All LLM inference → DHQ dispatcher, never direct Ollama from modules
- User is REMOTE — 192.168.1.200, never localhost
- Never commit to main directly

## Session Stats
${STATS}"

CONTEXT_JSON=$(echo "$CONTEXT" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" 2>/dev/null)

cat <<HOOK_JSON
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": ${CONTEXT_JSON}
  }
}
HOOK_JSON
