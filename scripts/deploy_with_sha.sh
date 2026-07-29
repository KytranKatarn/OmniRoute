#!/usr/bin/env bash
# Deploy an image-baked product WITH its git commit stamped into the image, so
# /version reports what is actually running and scripts/deploy_drift_check.py can
# catch deploy-from-feature-branch drift (KB mistake #279350).
#
# Usage: scripts/deploy_with_sha.sh <compose-dir> <service> [service...]
#   e.g. scripts/deploy_with_sha.sh standalone/media_hub mediahub_app
#        scripts/deploy_with_sha.sh kytran-business-suite kytran-business-suite kbs-worker
#
# THE SHA COMES FROM THE REPO THAT OWNS <compose-dir>, NOT FROM THE CALLER'S CWD.
# This used to be `git rev-parse --show-toplevel` against $PWD, which silently
# stamped the WRONG repository whenever the product was its own git repo nested
# inside the platform checkout — true for kytran-business-suite, kytran-creed and
# kytran-server-manager. On 2026-07-29 that stamped archie-platform's commit
# f63ef4e04 onto the KBS image; f63ef4e04 is not even a valid object in the KBS
# repo (task #5401). A wrong stamp is worse than a missing one: "unknown" is an
# honest unknown, a foreign SHA is confidently false, and deploy_drift_check.py
# compares the baked SHA against the product repo's head.
#
# Guardrail: refuses to build the PRODUCTION container from a non-main / dirty
# tree unless ALLOW_DIRTY_DEPLOY=1 — the production image must only ever come
# from the integrated main. Use ALLOW_DIRTY_DEPLOY=1 for a throwaway test build
# on a feature branch (and ideally a different image tag / container name).
set -euo pipefail

DIR="${1:?compose dir required (e.g. standalone/media_hub)}"
shift
if [ "$#" -lt 1 ]; then
  echo "✗ at least one service name required (e.g. mediahub_app)" >&2
  echo "  Usage: $0 <compose-dir> <service> [service...]" >&2
  exit 64
fi
SVCS=("$@")

# --- resolve the compose dir ------------------------------------------------
# Accept an absolute path, a path relative to cwd, or (back-compat with the
# documented usage) a path relative to the CALLER's repo root.
if [ -d "$DIR" ]; then
  DIR_ABS="$(cd "$DIR" && pwd)"
elif CALLER_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" && [ -d "$CALLER_ROOT/$DIR" ]; then
  DIR_ABS="$(cd "$CALLER_ROOT/$DIR" && pwd)"
else
  echo "✗ compose dir not found: '$DIR'" >&2
  exit 66
fi

if ! compgen -G "$DIR_ABS/docker-compose*.y*ml" >/dev/null; then
  echo "✗ no docker-compose file in '$DIR_ABS' — refusing to guess." >&2
  exit 66
fi

# --- derive the SHA from the repo that OWNS that dir ------------------------
if ! REPO_ROOT="$(git -C "$DIR_ABS" rev-parse --show-toplevel 2>/dev/null)"; then
  echo "✗ '$DIR_ABS' is not inside a git repository — cannot stamp a commit." >&2
  echo "  Refusing to deploy rather than stamp something false." >&2
  exit 65
fi

# Fail loudly on the case this script got wrong before: the compose dir must
# actually live under the repo we are about to take the SHA from.
case "$DIR_ABS/" in
  "$REPO_ROOT"/*) : ;;
  *)
    echo "✗ '$DIR_ABS' is not contained in resolved repo '$REPO_ROOT'." >&2
    exit 65
    ;;
esac

BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
DIRTY=""
git -C "$REPO_ROOT" diff --quiet || DIRTY="+dirty"

# Untracked files ARE copied into the image by a `COPY .` Dockerfile (KBS has no
# .dockerignore), so the artifact can contain code that exists in no commit while
# the stamp claims a clean one. Warn loudly, but do NOT refuse — untracked noise
# is common — and do NOT alter GIT_SHA, which drift-checking compares verbatim.
UNTRACKED="$(git -C "$REPO_ROOT" ls-files --others --exclude-standard | wc -l | tr -d ' ')"

if { [ "$BRANCH" != "main" ] || [ -n "$DIRTY" ]; } && [ "${ALLOW_DIRTY_DEPLOY:-0}" != "1" ]; then
  echo "⚠️  Refusing to deploy '${SVCS[*]}' from '$BRANCH${DIRTY}'."
  echo "    The production container must be built from a clean, integrated main (KB #279350)."
  echo "    Merge first, or set ALLOW_DIRTY_DEPLOY=1 for a throwaway test build."
  exit 2
fi

export GIT_SHA="${SHA}${DIRTY}"
export BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Print the repo being stamped. The old version printed only "branch=main",
# which looked perfectly healthy while stamping a different repository.
echo "→ repo     : $REPO_ROOT"
echo "→ remote   : $(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo '(none)')"
echo "→ compose  : $DIR_ABS"
echo "→ building : ${SVCS[*]} @ ${GIT_SHA} (branch=${BRANCH})"
if [ "$UNTRACKED" -gt 0 ]; then
  echo "⚠️  $UNTRACKED untracked file(s) in $REPO_ROOT will be BAKED INTO the image"
  echo "    but exist in no commit — the stamp will claim a clean tree. Commit or remove them."
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN=1 — resolution only, nothing built."
  exit 0
fi

cd "$DIR_ABS"
docker compose up -d --build "${SVCS[@]}"
echo "✓ deployed '${SVCS[*]}' @ ${GIT_SHA}. Verify the running image reports this commit:"
echo "    scripts/deploy_drift_check.py"
