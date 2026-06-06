# Codex CLI container — the isolation boundary for `codex exec`.
# Mounts only the worktree (rw) + the repo .git (ro) + a per-run CODEX_HOME.
# Holds NO DB creds — only a read-scoped MCP bearer (ARCHIE_KB_BEARER) for the
# archie_kb gateway. Because the container IS the sandbox, codex runs with its own
# sandbox bypassed inside (see run-codex-task.sh).
FROM node:22-slim

# git + ripgrep: codex's shell tool uses these to read/inspect the worktree.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Codex CLI (latest, same as the host install — streamable-HTTP MCP + exec
# flags verified on the host). Pin here later once a known-good npm version is chosen.
RUN npm install -g @openai/codex

WORKDIR /work
ENTRYPOINT ["codex"]
