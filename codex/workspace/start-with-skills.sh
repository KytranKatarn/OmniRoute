#!/bin/sh
# Install the repo-versioned A.R.C.H.I.E. skills into the persistent Codex home,
# then launch the existing terminal entrypoint.
set -eu

CODEX_SKILLS_HOME="${CODEX_HOME:-/codex-home}/skills"
mkdir -p "$CODEX_SKILLS_HOME"

# Refresh only the versioned A.R.C.H.I.E. skill names. Other personal/system
# skills in CODEX_HOME remain untouched.
for skill_dir in /opt/archie-codex-skills/archie-*; do
  [ -d "$skill_dir" ] || continue
  cp -R "$skill_dir" "$CODEX_SKILLS_HOME/"
done

exec /start.sh "$@"
