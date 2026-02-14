#!/bin/bash
# Cleanup idle tmux claude-code sessions after a configurable timeout.
# Runs via systemd timer (hourly). When killed, the next ttyd connection
# auto-creates a fresh session thanks to tmux's -A flag.

TMUX_SESSION="claude-code"
IDLE_TIMEOUT_SECONDS=${IDLE_TIMEOUT_SECONDS:-172800}  # 48 hours

# Check if session exists
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    exit 0
fi

# Get last activity timestamp (epoch seconds)
LAST_ACTIVITY=$(tmux display-message -t "$TMUX_SESSION" -p '#{session_activity}' 2>/dev/null)
if [ -z "$LAST_ACTIVITY" ]; then
    exit 0
fi

NOW=$(date +%s)
IDLE_SECONDS=$((NOW - LAST_ACTIVITY))
IDLE_HOURS=$((IDLE_SECONDS / 3600))

if [ "$IDLE_SECONDS" -ge "$IDLE_TIMEOUT_SECONDS" ]; then
    echo "$(date -Iseconds) Killing tmux session '$TMUX_SESSION' — idle ${IDLE_HOURS}h (limit: $((IDLE_TIMEOUT_SECONDS/3600))h)"
    tmux kill-session -t "$TMUX_SESSION"
else
    echo "$(date -Iseconds) Session '$TMUX_SESSION' active — idle ${IDLE_HOURS}h (limit: $((IDLE_TIMEOUT_SECONDS/3600))h)"
fi
