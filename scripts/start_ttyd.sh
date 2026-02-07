#!/bin/bash
# Start ttyd with Claude CLI for ARCHIE platform
# Access at: http://192.168.1.200:7681

TTYD_PORT=${TTYD_PORT:-7681}
TTYD_USER=${TTYD_USER:-admin}
TTYD_PASS=${TTYD_PASS:-archie2026}

echo "Starting ttyd on port $TTYD_PORT..."
echo "Access: http://$(hostname -I | awk '{print $1}'):$TTYD_PORT"

# Start ttyd with:
# -p: port
# -c: credentials (user:pass)
# -W: writable (allow input)
# -t: terminal options
exec ttyd \
    -p "$TTYD_PORT" \
    -c "$TTYD_USER:$TTYD_PASS" \
    -W \
    -t fontSize=14 \
    -t fontFamily="JetBrains Mono, Consolas, monospace" \
    -t cursorBlink=true \
    -t theme='{"background": "#1a1a2e", "foreground": "#00ff41"}' \
    claude
