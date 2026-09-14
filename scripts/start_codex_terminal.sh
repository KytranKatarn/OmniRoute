#!/bin/sh
# In-container launcher for the CONTAINED Codex web terminal.
# Runs interactive `codex` in a tmux session exposed via ttyd. The container bounds the
# FILESYSTEM: no host fs (except a read-only auth.json seed), no DB creds. Workspace is
# the /work volume.
#
# ⚠️ It is NOT a sandbox, and this header said "SANDBOXED … read-scoped MCP bearer"
# until 2026-09-13. The bearer is now read+write (owner decision): through
# archie_mcp_gateway this lane creates and closes Dev HQ tasks, manages team members
# and spends fleet compute. It still holds no DB credential and cannot approve its own
# work. Scope set: platform_v2/services/internal_auth.py, caller `coder_lanes`.
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
# Model provider — OmniRoute, the self-hosted OpenAI-compatible gateway (#6653).
#
# Added 2026-09-13. Until then this file declared NO provider at all, so codex fell back
# to its built-in OpenAI/ChatGPT default whose auth is dead (auth.json.dead) — the lane
# could reach the platform but could not run a single inference. It also could not have
# reached omniroute if it tried: the service was on opencode's network and not codex's,
# so the hostname was ENOTFOUND. Both halves are fixed; neither alone was enough.
#
# ⚠️ The key is read from the ENVIRONMENT by name and is never written into this file.
# opencode stores the same credential inline in opencode.json; do not copy that here.
# auto/coding:free keeps the lane on the FREE tier per the standing no-paid-keys rule.
model_provider = "omniroute"
model = "${OMNIROUTE_MODEL:-auto/coding:free}"

# ⚠️ NO BACKTICKS ANYWHERE BELOW — this heredoc is <<EOF (UNQUOTED) because it must
# expand $OMNIROUTE_*. That also makes a backtick COMMAND SUBSTITUTION, even inside a
# comment: on 2026-09-13 a comment reading "caught by <backtick>codex doctor<backtick>"
# executed codex doctor and pasted its output into this file, and codex then refused it
# with "key with no value" on a line of that output. Use plain words, never backticks.
#
# ⚠️ ROOT KEYS MUST STAY ABOVE EVERY [table] HEADER. In TOML a bare key after a header
# belongs to THAT table — placing model_provider/model below [projects."/work/..."] put
# them INSIDE the projects table and codex refused the whole file ("failed to load Codex
# config", caught by codex doctor on 2026-09-13). Anything added below is a table.
[projects."/work"]
trust_level = "trusted"

[projects."/work/archie-platform"]
trust_level = "trusted"

[model_providers.omniroute]
name = "OmniRoute"
base_url = "${OMNIROUTE_BASE_URL:-http://omniroute:20128/v1}"
env_key = "OMNIROUTE_API_KEY"
# codex 0.154.0 REMOVED wire_api="chat" ("no longer supported", openai/codex#7782), so a
# chat-completions provider must be declared as "responses" here. Verified against this
# gateway with an AUTHENTICATED probe: /v1/responses answers 400 on an empty body while a
# bogus /v1/... path answers 404, so the route genuinely exists. An UNauthenticated probe
# cannot tell you this — omniroute runs auth BEFORE routing and 401s every /v1/ path,
# including ones that do not exist.
wire_api = "responses"

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
