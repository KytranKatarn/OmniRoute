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
rm -f /tmp/tmux-1000/default 2>/dev/null || true

# Pre-create the tmux session with bash (Claude CLI exits in detached sessions).
# Then send the claude command into the live bash session.
tmux new-session -d -s "$TMUX_SESSION"
sleep 0.5
tmux send-keys -t "$TMUX_SESSION" '/home/kytran/.local/bin/claude' Enter

# Start ttyd with:
# -p: port
# -i: interface — 127.0.0.1 ONLY. ttyd here is the UNAUTHENTICATED backend;
#     ttyd_auth_proxy.py on :7681 is the only thing allowed to reach it. Binding
#     this to 0.0.0.0 publishes a WRITABLE shell to the whole LAN and bypasses the
#     proxy entirely — it was 0.0.0.0 in production and served HTTP 200 with no auth.
# -W: writable (allow input)
# -t: terminal options
# tmux attach: reconnects to the persistent claude session
exec ttyd \
    -p "$TTYD_PORT" \
    -i 127.0.0.1 \
    -W \
    -t fontSize=14 \
    -t fontFamily="JetBrains Mono, Consolas, monospace" \
    -t cursorBlink=true \
    -t theme='{"background": "#1a1a2e", "foreground": "#00ff41"}' \
    tmux attach-session -t "$TMUX_SESSION"
