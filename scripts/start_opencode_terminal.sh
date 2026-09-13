#!/bin/sh
# In-container launcher for the CONTAINED OpenCode web terminal.
#
# Mirrors start_codex_terminal.sh deliberately: same tmux-in-ttyd shape, same
# one-viewer rule, same "the container bounds the filesystem" posture. Differences
# from codex are only where opencode genuinely differs.
#
# ⚠️ Contained is NOT sandboxed — see the note in start_codex_terminal.sh. This lane
# carries the same read+write gateway bearer and the same platform reach.
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

# ---------------------------------------------------------------------------
# Gateway bearer — rendered from the MOUNTED SECRET on every start (#6749 follow-on).
#
# ⚠️ opencode has no `bearer_token_env_var` escape hatch like codex's config.toml: its
# MCP block takes a LITERAL Authorization header. So the secret has to land in the file.
# It lands in the VOLUME copy, never in the image — `opencode.json` is not COPYed by
# Dockerfile.terminal, and nothing here writes back to the host.
#
# Rewriting EVERY start is the point, not laziness. The bearer was pasted in by hand
# once; when `provision_coder_lane_keys.sh` rotated the lane keys on 2026-09-13 the
# pasted one was deactivated and this lane went on presenting a DEAD key — a 401 that
# reads to the user as "the KB tools are broken". A start-time render means a rotation
# is picked up by a restart, with no one editing JSON.
#
# The whole file is rewritten through a JSON parse so the provider/model settings around
# it survive; a sed on the Authorization line would corrupt the file the first time the
# key contained a `/` or `&`.
if [ -f /run/secrets/opencode_kb_bearer ]; then
    OC_CFG="$XDG_CONFIG_HOME/opencode/opencode.json"
    mkdir -p "$(dirname "$OC_CFG")"
    [ -f "$OC_CFG" ] || echo '{"$schema":"https://opencode.ai/config.json"}' > "$OC_CFG"
    # node, not python3/jq: opencode IS a node program, so node is the one interpreter
    # this image cannot lose. jq is not installed.
    OC_CFG="$OC_CFG" node -e '
      const fs = require("fs");
      const p = process.env.OC_CFG;
      // trim: a trailing newline in the secret file becomes a header that never matches
      const key = fs.readFileSync("/run/secrets/opencode_kb_bearer", "utf8").trim();
      const c = JSON.parse(fs.readFileSync(p, "utf8"));
      c.mcp = c.mcp || {};
      const m = c.mcp["archie-kb"] = c.mcp["archie-kb"] || {};
      m.type = "remote";
      m.url = m.url || "http://archie_mcp_gateway:7800/mcp";
      m.enabled = true;
      m.headers = Object.assign({}, m.headers, { Authorization: "Bearer " + key });
      fs.writeFileSync(p, JSON.stringify(c, null, 2) + "\n");
      // length only — never the value
      console.error("[opencode] gateway bearer rendered from secret (" + key.length + " chars)");
    ' || echo "[opencode] WARNING: could not render the gateway bearer — KB tools will 401" >&2
    chmod 600 "$OC_CFG" 2>/dev/null || true
else
    echo "[opencode] WARNING: /run/secrets/opencode_kb_bearer is not mounted — KB tools will 401" >&2
fi

# Start IN THE REPO, not the bare volume. Until 2026-09-12 /work held only scratch
# files (hello.py) and the lane had nothing to work on — the repo is now cloned to
# /work/archie-platform, so land there or opencode opens with no codebase in scope.
cd /work/archie-platform 2>/dev/null || cd /work

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
