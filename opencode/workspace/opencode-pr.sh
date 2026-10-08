#!/usr/bin/env bash
# opencode-pr — from inside the OpenCode web terminal: commit (if needed), push the
# current opencode/* branch, and open a PR against main. F.O.R.G.E. (Repair Bay)
# picks the PR up for review; a human merges. NEVER merges.
#
# Deliberately a mirror of codex/workspace/codex-pr.sh rather than a new design: the
# two lanes should ship the same way, and a second shape is a second thing to audit.
# The differences are exactly three — the lane name, the branch prefix, and the
# secret it reads.
#
# Usage:
#   opencode-pr "fix(therapy): guard the empty-session case"
#
# Requires: /run/secrets/opencode_github_token — a fine-grained PAT scoped to THIS
# repo with Contents + Pull requests write, and NOTHING else.
#
# /run/secrets/opencode_github_token IS mounted, deliberately — the owner
# confirmed this on 2026-09-28. Measured: present in all three instances
# (canonical 17685, guarded 17686, guard-free 17687), a 94-byte file bind-mounted
# read-only from secrets/opencode/github_token.txt.
#
# Having it is NOT permission to use it. This lane still never merges, never
# approves its own PR, and ships only via this script. The credential is
# fine-grained (Contents + Pull requests write) and "Pull requests: write" is
# indivisible on GitHub, so this token COULD merge a PR — which is why branch
# protection on main is load-bearing here, not ceremonial. Treat the token as
# plumbing: never print, echo, log or commit it, never put it on a command line,
# never write it into a file in the repo.
#
# ⚠️ "Pull requests: write" is not divisible on GitHub — it permits merging as well
# as opening. So the token alone cannot stop a merge from here; the /usr/local/bin/gh
# guard and, properly, a non-zero required_approving_review_count on main are what do.
set -euo pipefail

TITLE="${1:?usage: opencode-pr \"<pr title>\"}"
REPO_SLUG="KytranKatarn/archie-platform"
TOKEN_FILE="/run/secrets/opencode_github_token"
[ -s "$TOKEN_FILE" ] || {
    echo "opencode-pr: missing $TOKEN_FILE — this lane has no GitHub credential."
    echo "  Mounting one is an owner decision (see the header of this script)."
    echo "  You can still commit locally; you cannot push or open a PR."
    exit 1
}

# ⚠️ REFUSE TO SHIP FROM THE LIVE SHARED TREE.
#
# Since option B this lane also mounts /mnt/archie_brain — the OWNER'S working
# checkout. Two independent reasons this helper must not run there:
#
#   1. `git add -A` below would sweep whatever the owner has in progress into this
#      lane's commit. That is not hypothetical: an untracked .oc-lane-test/ (a full
#      platform_v2 copy) was swept into an index exactly this way on 2026-09-13.
#   2. That tree's core.hooksPath points at its OWN .git/hooks, NOT the baked
#      /opt/*-guard — measured live 2026-09-14 in both lanes. So a push from there
#      runs with NO scope guard. Re-pointing it would overwrite the owner's hooks,
#      so the answer is not to push from there.
#
# The live tree is for editing, restarting and verifying the platform. Shipping
# happens from this lane's own clone, on its own branch.
TOPLEVEL="$(git rev-parse --show-toplevel)"
if [ "$TOPLEVEL" = "/mnt/archie_brain" ]; then
  echo "REFUSED: this is the owner's live checkout (/mnt/archie_brain), not a lane clone."
  echo "  Shipping from here would commit the owner's in-progress work and would run"
  echo "  with no scope guard. Work in the lane clone instead, then re-run."
  exit 1
fi
cd "$TOPLEVEL"

# Refuse to work on main — carve an opencode/ branch from the current state.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  SLUG="$(echo "$TITLE" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
  BRANCH="opencode/${SLUG}-$(date +%s)"
  git switch -c "$BRANCH"
fi
case "$BRANCH" in opencode/*) : ;; *) echo "opencode-pr: branch must start with opencode/"; exit 1;; esac

# Commit any pending work under this title (no-op if tree already clean/committed).
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  git commit -q -m "$TITLE

Authored interactively via the OpenCode web terminal." || true
fi

# Push — in guarded lanes this fires the pre-push scope guard (fails closed if
# out of scope); the guard-free lane runs with no guard (/opt/no-guard).
git push -u origin "$BRANCH"

# Open the PR via the GitHub API (python urllib; the image has no curl, same as codex).
python3 - "$REPO_SLUG" "$BRANCH" "$TITLE" "$TOKEN_FILE" <<'PY'
import json, sys, urllib.request, urllib.error
repo, branch, title, token_file = sys.argv[1:5]
token = open(token_file).read().strip()
body = json.dumps({
    "title": title,
    "head": branch,
    "base": "main",
    "body": "Opened from the OpenCode web terminal (interactive). "
            "F.O.R.G.E. review required before merge.\n\n🤖 OpenCode (CLI)",
}).encode()
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/pulls", data=body, method="POST",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
             "User-Agent": "opencode-terminal"},
)
try:
    r = urllib.request.urlopen(req, timeout=30)
    print("PR opened:", json.load(r).get("html_url"))
except urllib.error.HTTPError as e:
    msg = e.read().decode()
    if "A pull request already exists" in msg:
        print(f"PR already open for {branch} — pushed new commits to it.")
    else:
        print("PR creation failed:", e.code, msg); sys.exit(1)
PY
