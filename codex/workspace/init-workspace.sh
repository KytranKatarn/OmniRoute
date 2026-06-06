#!/bin/sh
# init-workspace.sh — prepare the interactive Codex workspace inside the terminal
# container: clone/sync the repo into /work, wire a token credential helper (token
# never persisted to disk), install the in-repo scope-guard hook, and expose
# codex-pr on PATH. Idempotent; safe to run on every container start.
#
# Gated on /run/secrets/codex_github_token. If absent, the terminal still launches
# (read-only chat + KB), just without a working repo.
set -e

REPO_SLUG="KytranKatarn/archie-platform"
REPO_DIR="/work/archie-platform"
TOKEN_FILE="/run/secrets/codex_github_token"

if [ ! -s "$TOKEN_FILE" ]; then
  echo "[init-workspace] No GitHub token at $TOKEN_FILE — skipping repo setup."
  echo "[init-workspace] (Chat + read-only KB still work. Add the PAT secret to enable edits.)"
  exit 0
fi

# Credential helper reads the secret on demand → token never lands in .git/config.
git config --global credential.helper \
  '!f() { echo username=x-access-token; echo "password=$(cat /run/secrets/codex_github_token)"; }; f'
git config --global user.name "Codex (CLI)"
git config --global user.email "codex@kytranempowerment.com"
git config --global --add safe.directory "$REPO_DIR"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "[init-workspace] Cloning $REPO_SLUG into $REPO_DIR ..."
  git clone "https://github.com/$REPO_SLUG.git" "$REPO_DIR"
else
  echo "[init-workspace] Syncing existing clone to origin/main ..."
  git -C "$REPO_DIR" fetch -q origin
  git -C "$REPO_DIR" checkout -q main 2>/dev/null || git -C "$REPO_DIR" checkout -q -b main origin/main
  git -C "$REPO_DIR" reset --hard origin/main
fi

# Scope-guard hook is BAKED into the image at /opt/codex-guard (hook + allowlist),
# independent of what the cloned branch contains and NOT editable from the working
# tree — so repo edits cannot loosen the guard. (codex-pr is baked on PATH too.)
git -C "$REPO_DIR" config core.hooksPath /opt/codex-guard

echo "[init-workspace] Ready. Workspace: $REPO_DIR (branch main, scope-guarded via /opt/codex-guard)."
