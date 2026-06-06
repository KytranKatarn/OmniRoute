#!/bin/sh
# In-container launcher for the SANDBOXED Codex web terminal.
# Runs interactive `codex` in a tmux session exposed via ttyd. The container is the
# sandbox: no host fs (except a read-only auth.json seed), no DB creds — only a
# read-scoped MCP bearer for the archie_kb gateway. Workspace is the /work volume.
set -e

CODEX_HOME="${CODEX_HOME:-/codex-home}"
mkdir -p "$CODEX_HOME"

# Seed Codex auth from the mounted docker secret on first start (token refresh then
# writes to this writable CODEX_HOME copy, never back to the host).
[ -f /run/secrets/codex_auth ] && [ ! -f "$CODEX_HOME/auth.json" ] \
  && cp /run/secrets/codex_auth "$CODEX_HOME/auth.json" || true
chmod 600 "$CODEX_HOME/auth.json" 2>/dev/null || true

# Read-scoped KB bearer from the mounted secret → env var referenced by config.toml.
[ -f /run/secrets/codex_kb_bearer ] && ARCHIE_KB_BEARER="$(cat /run/secrets/codex_kb_bearer)" && export ARCHIE_KB_BEARER

# Codex config: trust the workspace + wire the read-only KB MCP gateway (bearer only).
cat > "$CODEX_HOME/config.toml" <<EOF
[projects."/work"]
trust_level = "trusted"

[projects."/work/archie-platform"]
trust_level = "trusted"

# Live read-only knowledge access — the container holds ONLY this bearer (no DB creds).
[mcp_servers.archie_kb]
url = "${ARCHIE_KB_GATEWAY:-http://archie_mcp_gateway:7800/mcp}"
bearer_token_env_var = "ARCHIE_KB_BEARER"
EOF

# Prepare the working repo: clone/sync into /work, wire token credential helper,
# install the scope-guard hook, expose codex-pr. No-op if the PAT secret is absent.
sh /init-workspace.sh || echo "[start] init-workspace failed — launching without a repo"

# Launch Codex inside the repo if present, else the bare /work volume.
WORKDIR=/work
[ -d /work/archie-platform/.git ] && WORKDIR=/work/archie-platform
cd "$WORKDIR"
tmux kill-session -t codex 2>/dev/null || true
tmux new-session -d -s codex
# --dangerously-bypass-approvals-and-sandbox is safe: the CONTAINER is the boundary
# (no host fs/secrets, cap_drop ALL). Codex's own bwrap can't start on this host.
tmux send-keys -t codex 'codex --dangerously-bypass-approvals-and-sandbox' Enter

# --max-clients 1: one viewer only (no shared-session join). Reachability is
# restricted to the dedicated codex_terminal_net + the host-published localhost port.
exec ttyd -p 7681 -i 0.0.0.0 -W --max-clients 1 \
  -t fontSize=14 -t 'theme={"background":"#1a1a2e","foreground":"#00ff41"}' \
  tmux attach-session -t codex
