#!/bin/sh
# In-container launcher for the SANDBOXED OpenCode web terminal.
#
# Mirrors start_codex_terminal.sh deliberately: same tmux-in-ttyd shape, same
# one-viewer rule, same "the container is the sandbox" posture. Differences from
# codex are only where opencode genuinely differs.
set -e

OPENCODE_HOME="${OPENCODE_HOME:-/opencode-home}"
export XDG_CONFIG_HOME="$OPENCODE_HOME/config"
export XDG_DATA_HOME="$OPENCODE_HOME/data"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" /work

# Seed auth from the mounted docker secret on first start only. opencode refreshes
# tokens into its own writable home, never back onto the host file — the secret is
# a SEED, not the live store.
if [ -f /run/secrets/opencode_auth ] && [ ! -f "$XDG_DATA_HOME/opencode/auth.json" ]; then
    mkdir -p "$XDG_DATA_HOME/opencode"
    cp /run/secrets/opencode_auth "$XDG_DATA_HOME/opencode/auth.json"
    chmod 600 "$XDG_DATA_HOME/opencode/auth.json" 2>/dev/null || true
fi

cd /work

# ⚠️ Kill a stale session by EXACT name. `tmux kill-server` would also take out any
# other session in this container, and a bare prefix match can hit a neighbour.
tmux kill-session -t opencode 2>/dev/null || true
tmux new-session -d -s opencode

# Respawn rather than drop to a shell. If opencode exits — crash, upgrade, a stray
# Ctrl-D — a bare `tmux send-keys <binary>` leaves the viewer sitting at an
# interactive SHELL inside the container. That is a strictly larger capability than
# the lane advertises, and the user gets it silently. Same fix as the archie-tui lane.
tmux send-keys -t opencode \
  "while true; do opencode; echo; echo '[opencode exited — restarting in 2s; this lane does not drop to a shell]'; sleep 2; done" Enter

# --max-clients 1: one viewer, no shared-session join, matching codex. Reachability
# is the dedicated network plus the host-published LOCALHOST port — the auth proxy
# on the host is the only public path in.
exec ttyd -p 7681 -i 0.0.0.0 -W --max-clients 1 \
  -t fontSize=14 -t 'theme={"background":"#1a1a2e","foreground":"#fbbf24"}' \
  tmux attach-session -t opencode
