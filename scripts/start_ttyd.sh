#!/bin/bash
# Start ttyd with Claude CLI for ARCHIE platform
# Internal-only: bound to localhost, auth handled by ttyd_auth_proxy.py
# Access at: http://192.168.1.200:7681 (via auth proxy)
# Uses tmux for session persistence — browser disconnect doesn't kill claude

TTYD_PORT=${TTYD_PORT:-17681}
TMUX_SESSION="claude-code"

echo "Starting ttyd on 127.0.0.1:$TTYD_PORT (internal, no auth)..."
echo "Auth proxy handles external access on port 7681"
echo "tmux session: $TMUX_SESSION (persistent across browser disconnects)"

# Kill any stale tmux session on startup (clean slate for service restart)
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

# Start ttyd with:
# -p: port
# -i: interface (lo = localhost only)
# -W: writable (allow input)
# -t: terminal options
# tmux new-session -A: attach if exists, create if not
exec ttyd \
    -p "$TTYD_PORT" \
    -i lo \
    -W \
    -t fontSize=14 \
    -t fontFamily="JetBrains Mono, Consolas, monospace" \
    -t cursorBlink=true \
    -t theme='{"background": "#1a1a2e", "foreground": "#00ff41"}' \
    tmux new-session -A -s "$TMUX_SESSION"
