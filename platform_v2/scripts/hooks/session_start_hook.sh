#!/bin/bash
# SessionStart Hook - Load A.R.C.H.I.E. context at conversation start
# Provides memory system integration for Claude Code

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║           A.R.C.H.I.E. Memory System Active                           ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"

# Check platform health quickly
PLATFORM_STATUS=$(curl -s --max-time 2 http://localhost:3000/tools/blueprint/api/status 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$PLATFORM_STATUS" ]; then
    VERSION=$(echo "$PLATFORM_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version', 'unknown'))" 2>/dev/null || echo "unknown")
    echo "Platform v$VERSION - Online"
else
    echo "Platform: Offline (start with: docker-compose up -d)"
fi

# Show current git context
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git")
GIT_COMMIT=$(git log -1 --format="%h %s" 2>/dev/null | head -c 60 || echo "no commits")
echo "Branch: $GIT_BRANCH | Last: $GIT_COMMIT"

# Check for any recent mistakes learned (last 24h)
RECENT_MISTAKES=$(curl -s --max-time 2 "http://localhost:3000/tools/consciousness/api/mistakes/recent?hours=24" 2>/dev/null)
MISTAKE_COUNT=$(echo "$RECENT_MISTAKES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('mistakes', [])))" 2>/dev/null || echo "0")
if [ "$MISTAKE_COUNT" != "0" ] && [ "$MISTAKE_COUNT" != "" ]; then
    echo "Recent mistakes learned: $MISTAKE_COUNT (check before similar tasks)"
fi

echo ""
