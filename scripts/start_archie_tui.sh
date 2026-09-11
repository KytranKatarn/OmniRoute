#!/bin/bash
# Start ttyd running the A.R.C.H.I.E. TUI — the PLATFORM lane.
# Internal-only: bound to 127.0.0.1; auth is ttyd_auth_proxy.py on :7684.
# Mirrors start_ttyd.sh (the claude lane) deliberately — owner decision 2026-09-11:
# this lane edits the PLATFORM, so it runs on the host beside archie_engine rather
# than in a container. archie_engine publishes on 127.0.0.1:9090 ONLY, so a
# containerised TUI would have to be handed a path to it.

TTYD_PORT=${TTYD_PORT:-17683}
TMUX_SESSION="archie-tui"
TUI_BIN=${ARCHIE_TUI_BIN:-/mnt/archie_brain/bin/archie-tui}

# ⚠️ The TUI reads ARCHIE_ENGINE_TOKEN; the engine's own variable is ENGINE_WS_TOKEN.
# The names differ, so the mapping is explicit here. Empty ⇒ the engine answers 401 on
# the ws handshake (verified 2026-09-11: 101 with the bearer, 401 without, 401 wrong).
if [ -z "${ARCHIE_ENGINE_TOKEN:-}" ] && [ -r /mnt/archie_brain/.env ]; then
    ARCHIE_ENGINE_TOKEN="$(grep -m1 '^ENGINE_WS_TOKEN=' /mnt/archie_brain/.env | cut -d= -f2- | tr -d '\r\n')"
    export ARCHIE_ENGINE_TOKEN
fi

# Fail LOUD. A missing binary must not leave a bare shell serving on the lane.
if [ ! -x "$TUI_BIN" ]; then
    echo "FATAL: archie-tui binary not found or not executable at $TUI_BIN" >&2
    echo "Build it:  cd /mnt/standalone/archie-code/archie-tui && go build -o $TUI_BIN ." >&2
    exit 1
fi
if [ -z "${ARCHIE_ENGINE_TOKEN:-}" ]; then
    echo "FATAL: no ARCHIE_ENGINE_TOKEN (and none readable from .env ENGINE_WS_TOKEN)." >&2
    echo "The engine refuses an unauthenticated ws handshake with 401." >&2
    exit 1
fi

echo "Starting ttyd on 127.0.0.1:$TTYD_PORT (internal, no auth of its own)"
echo "Auth proxy handles external access on port 7684"
echo "tmux session: $TMUX_SESSION (persistent across browser disconnects)"

tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

# Same shape as the claude lane: a live bash session, then send the command into it.
# ⚠️ CONSEQUENCE, and it is the one to fix before any non-admin ever reaches this lane:
# because the TUI runs INSIDE tmux, quitting the TUI leaves the viewer at a HOST SHELL.
# That is acceptable today — the mint is admin-only and this lane is marked HOST — but
# the approved-staff allowlist work MUST close it (respawn the TUI, or a restricted
# shell), or "staff get the TUI" silently becomes "staff get a host shell".
# ⚠️ RESPAWN, do not fall through to the shell. The TUI runs under a supervisor loop so
# that QUITTING IT RESTARTS IT rather than leaving the viewer at a host shell. Without
# this, "approved staff get the archie-tui lane" silently means "approved staff get a
# host shell on the platform box" — the lane's whole safety argument is that it is a
# constrained TUI, not a shell.
#
# The loop is written into the tmux session as a command, so an operator who genuinely
# needs a shell can still detach (C-b d) and use the claude lane, which is HONESTLY
# labelled as a host shell. Ctrl-C inside the TUI just brings the TUI back.
tmux new-session -d -s "$TMUX_SESSION"
sleep 0.5
tmux send-keys -t "$TMUX_SESSION" \
    "while true; do ARCHIE_ENGINE_TOKEN='$ARCHIE_ENGINE_TOKEN' $TUI_BIN; echo; echo '[archie-tui exited — restarting in 2s; this lane does not drop to a shell]'; sleep 2; done" Enter

# -i 127.0.0.1 ONLY. This ttyd is the UNAUTHENTICATED backend; the proxy on :7684 is
# the only thing allowed to reach it. Binding 0.0.0.0 here publishes a writable host
# surface to the LAN and bypasses the proxy — that has happened before on this box.
exec ttyd \
    -p "$TTYD_PORT" \
    -i 127.0.0.1 \
    -W \
    -t fontSize=14 \
    -t fontFamily="JetBrains Mono, Consolas, monospace" \
    -t cursorBlink=true \
    -t theme='{"background": "#1a1a2e", "foreground": "#00ff41"}' \
    tmux attach-session -t "$TMUX_SESSION"
