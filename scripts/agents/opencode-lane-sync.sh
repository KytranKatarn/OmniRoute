#!/usr/bin/env bash
# Refresh the opencode lane's platform clone — no credential in the lane, no root.
#
# #6736. Measured 2026-09-12: the lane's clone was frozen at the commit it was seeded
# with (3c442e1c2, 11:31) and was already five commits behind main by 13:30 the same
# day. Inside the container both directions fail:
#
#     git fetch          -> fatal: could not read Username for 'https://github.com'
#     git push --dry-run -> same
#
# No credential.helper, no GIT_ASKPASS, no ~/.git-credentials, no ~/.netrc — which is
# DELIBERATE. opencode/Dockerfile.terminal is explicit that the container is the
# isolation boundary: "no host filesystem, no platform DB credentials, its own volumes,
# cap_drop ALL". A third-party binary is exactly the thing you do not hand a GitHub
# token to.
#
# HOW THIS WORKS: the host already holds a complete checkout, so we hand the lane a git
# BUNDLE — a single file containing the objects — over `docker cp`, and fetch from it
# inside the container. No network, no authentication, no token anywhere near the lane,
# and no host filesystem mounted into it. The bundle is deleted afterwards.
#
# ⚠️ Why not just reach into the volume at /var/lib/docker/volumes/...: that path is
# root-only (`/var/lib/docker` is drwx--x--- root root), so it would force this whole
# script to run under sudo for no benefit. The docker socket is access the operator
# already has. Verified the hard way — the first draft of this script did exactly that
# and could not even see the clone.
#
# The archie_engine lane solves the same problem the other way: it holds a scoped
# ARCHIE_GITHUB_TOKEN and refreshes itself on start. That is a reasonable calculus for
# OUR code and a different one for a third-party binary. This keeps the decision to
# grant opencode a token OPEN rather than making it by default.
#
# Usage:  scripts/agents/opencode-lane-sync.sh [--force]
#         --force  discard uncommitted work in the lane (default: refuse and report)

set -euo pipefail

HOST_REPO="${HOST_REPO:-/mnt/archie_brain}"
CONTAINER="${CONTAINER:-archie_opencode_terminal}"
LANE_REPO="${LANE_REPO:-/work/archie-platform}"
BRANCH="${BRANCH:-main}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "container $CONTAINER not found" >&2
    exit 1
fi

# Run git in the lane as the user the lane ACTUALLY runs as, not docker exec's default.
# Reading it from the container rather than assuming is the point: the whole #6736 bug
# was a uid mismatch, and `docker exec -u node` succeeds where the real lane user fails,
# so a check run as the wrong user reports the lane healthy.
LANE_UID="$(docker inspect "$CONTAINER" --format '{{.Config.User}}')"
LANE_UID="${LANE_UID:-0}"
lane_git() { docker exec -u "$LANE_UID" "$CONTAINER" git -C "$LANE_REPO" "$@"; }

if ! lane_git rev-parse --git-dir >/dev/null 2>&1; then
    echo "no git clone at $LANE_REPO inside $CONTAINER — nothing to sync" >&2
    exit 1
fi

dirty="$(lane_git status --porcelain)"
if [ -n "$dirty" ] && [ "$FORCE" -eq 0 ]; then
    echo "REFUSING: the lane has uncommitted work. Sync would discard it:" >&2
    echo "$dirty" | sed 's/^/    /' >&2
    echo "Collect it first, or pass --force." >&2
    exit 2
fi

before="$(lane_git rev-parse --short HEAD)"

bundle="$(mktemp -t opencode-sync-XXXXXX.bundle)"
trap 'rm -f "$bundle"; docker exec -u "$LANE_UID" "$CONTAINER" rm -f /tmp/sync.bundle 2>/dev/null || true' EXIT

# --quiet keeps the progress chatter out; the bundle carries the whole branch so the
# lane can fast-forward from any age of staleness.
git -C "$HOST_REPO" bundle create "$bundle" "$BRANCH" --quiet 2>/dev/null \
    || git -C "$HOST_REPO" bundle create "$bundle" "$BRANCH" >/dev/null
docker cp "$bundle" "$CONTAINER:/tmp/sync.bundle"

lane_git fetch --quiet /tmp/sync.bundle "$BRANCH"

if [ "$FORCE" -eq 1 ] && [ -n "$dirty" ]; then
    echo "--force: discarding uncommitted lane work"
    lane_git reset --hard --quiet FETCH_HEAD
else
    # checkout -B, not merge --ff-only: the lane is a working copy that tracks main,
    # not a branch anyone develops on, so a detached or diverged lane should be
    # repaired silently rather than needing a human.
    lane_git checkout --quiet -B "$BRANCH" FETCH_HEAD
fi

after="$(lane_git rev-parse --short HEAD)"
if [ "$before" = "$after" ]; then
    echo "lane already current at $after"
else
    echo "lane $before -> $after"
    lane_git log --oneline -1
fi
