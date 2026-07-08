#!/usr/bin/env bash
# Deploy an image-baked product WITH its git commit stamped into the image, so
# /version reports what is actually running and scripts/deploy_drift_check.py can
# catch deploy-from-feature-branch drift (KB mistake #279350).
#
# Usage: scripts/deploy_with_sha.sh <compose-dir> <service>
#   e.g. scripts/deploy_with_sha.sh standalone/media_hub mediahub_app
#
# Guardrail: refuses to build the PRODUCTION container from a non-main / dirty
# tree unless ALLOW_DIRTY_DEPLOY=1 — the production image must only ever come
# from the integrated main. Use ALLOW_DIRTY_DEPLOY=1 for a throwaway test build
# on a feature branch (and ideally a different image tag / container name).
set -euo pipefail

DIR="${1:?compose dir required (e.g. standalone/media_hub)}"
SVC="${2:?service name required (e.g. mediahub_app)}"
REPO_ROOT="$(git rev-parse --show-toplevel)"

BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
DIRTY=""
git -C "$REPO_ROOT" diff --quiet || DIRTY="+dirty"

if { [ "$BRANCH" != "main" ] || [ -n "$DIRTY" ]; } && [ "${ALLOW_DIRTY_DEPLOY:-0}" != "1" ]; then
  echo "⚠️  Refusing to deploy '$SVC' from '$BRANCH${DIRTY}'."
  echo "    The production container must be built from a clean, integrated main (KB #279350)."
  echo "    Merge first, or set ALLOW_DIRTY_DEPLOY=1 for a throwaway test build."
  exit 2
fi

export GIT_SHA="${SHA}${DIRTY}"
export BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "→ building '$SVC' @ ${GIT_SHA} (branch=${BRANCH})"
cd "$REPO_ROOT/$DIR"
docker compose up -d --build "$SVC"
echo "✓ deployed '$SVC'. Verify the running image reports this commit:"
echo "    scripts/deploy_drift_check.py"
