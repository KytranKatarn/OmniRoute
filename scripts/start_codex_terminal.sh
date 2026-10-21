#!/bin/sh
# In-container launcher for the CONTAINED Codex web terminal.
# The existing host repository and Docker socket mounts confer host-equivalent
# authority. The container is not a security boundary for those mounts.
# DS9 is an opt-in profile; credentials are loaded only from its Docker secret.
set -e

CODEX_HOME="${CODEX_HOME:-/codex-home}"

# git refuses to operate on a repo owned by another uid ("detected dubious ownership").
# /mnt/archie_brain is owned by uid 1000 on the host and this lane runs as root, so
# WITHOUT this every git command in the live tree fails — which would defeat the whole
# point of mounting it. Scoped to the one path, not a blanket "*". Added 2026-09-13.
git config --global --add safe.directory /mnt/archie_brain 2>/dev/null || true

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
#
# Built-in OpenAI authentication stays available through plain codex.
# The opt-in DS9 provider lives in ds9.config.toml and contains no key.
[projects."/work"]
trust_level = "trusted"

[projects."/work/archie-platform"]
trust_level = "trusted"

# Live read-only knowledge access — the container holds ONLY this bearer (no DB creds).
[mcp_servers.archie_kb]
url = "${ARCHIE_KB_GATEWAY:-http://archie_mcp_gateway:7800/mcp}"
bearer_token_env_var = "ARCHIE_KB_BEARER"

# Lane capability parity (added 2026-10-16): the same public design-systems MCP server
# the opencode and claude lanes already reach (see .mcp.json). No secret involved, so
# nothing extra has to be mounted for this lane.
# hostinger-api is deliberately NOT listed here: it needs an API token that this bounded
# container has no mount for. Adding it means a new secret mount in docker-compose.yml,
# which is tracked separately from this change.
[mcp_servers.design_systems]
url = "https://design-systems-mcp.southleft.com/mcp"
EOF

# Install the opt-in profile without changing the existing direct login.
if [ -s /run/secrets/ds9_codex_gateway_api_key ]; then
  DS9_CODEX_API_KEY="$(cat /run/secrets/ds9_codex_gateway_api_key)"
  export DS9_CODEX_API_KEY
  python3 /opt/codex-ds9/write_profile.py
fi

# Prepare the working repo: clone/sync into /work, wire token credential helper,
# install the scope-guard hook, expose codex-pr. No-op if the PAT secret is absent.
sh /init-workspace.sh || echo "[start] init-workspace failed — launching without a repo"

# Launch Codex inside the repo if present, else the bare /work volume.
WORKDIR=/work
[ -d /work/archie-platform/.git ] && WORKDIR=/work/archie-platform
cd "$WORKDIR"
tmux kill-session -t codex 2>/dev/null || true
tmux new-session -d -s codex
# Keep the outer client's policy explicit. Container namespace denial must be
# fixed separately; never work around it by adding sandbox bypass or privilege.
if [ -n "${DS9_CODEX_API_KEY:-}" ]; then
  tmux send-keys -t codex 'codex-ds9' Enter
else
  tmux send-keys -t codex 'codex -a on-request --sandbox workspace-write' Enter
fi

# --max-clients 1: one viewer only (no shared-session join). Reachability is
# restricted to the dedicated codex_terminal_net + the host-published localhost port.
exec ttyd -p 7681 -i 0.0.0.0 -W --max-clients 1 \
  -t fontSize=14 -t 'theme={"background":"#1a1a2e","foreground":"#00ff41"}' \
  tmux attach-session -t codex
