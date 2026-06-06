#!/usr/bin/env bash
# codex-pr — from inside the Codex web terminal: commit (if needed), push the
# current codex/* branch, and open a PR against main. F.O.R.G.E. (Repair Bay)
# picks the PR up for review; a human merges. NEVER merges.
#
# Usage:
#   codex-pr "feat(faith): add reading-plan endpoint"     # title for commit+PR
#
# Requires: /run/secrets/codex_github_token (fine-grained PAT, this repo only,
# Contents+PR write). The push runs through the pre-push scope guard.
set -euo pipefail

TITLE="${1:?usage: codex-pr \"<pr title>\"}"
REPO_SLUG="KytranKatarn/archie-platform"
TOKEN_FILE="/run/secrets/codex_github_token"
[ -s "$TOKEN_FILE" ] || { echo "codex-pr: missing $TOKEN_FILE (PAT not configured)"; exit 1; }

cd "$(git rev-parse --show-toplevel)"

# Refuse to work on main — carve a codex/ branch from the current state.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  SLUG="$(echo "$TITLE" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)"
  BRANCH="codex/${SLUG}-$(date +%s)"
  git switch -c "$BRANCH"
fi
case "$BRANCH" in codex/*) : ;; *) echo "codex-pr: branch must start with codex/"; exit 1;; esac

# Commit any pending work under this title (no-op if tree already clean/committed).
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  git commit -q -m "$TITLE

Authored interactively via the Codex web terminal." || true
fi

# Push — this fires the pre-push scope guard (fails closed if out of scope).
git push -u origin "$BRANCH"

# Open the PR via the GitHub API (python urllib; the image has no curl).
python3 - "$REPO_SLUG" "$BRANCH" "$TITLE" "$TOKEN_FILE" <<'PY'
import json, sys, urllib.request, urllib.error
repo, branch, title, token_file = sys.argv[1:5]
token = open(token_file).read().strip()
body = json.dumps({
    "title": title,
    "head": branch,
    "base": "main",
    "body": "Opened from the Codex web terminal (interactive). "
            "Scope-guarded to allowed Applications/Concepts paths; "
            "F.O.R.G.E. review required before merge.\n\n🤖 Codex (CLI)",
}).encode()
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/pulls", data=body, method="POST",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
             "User-Agent": "codex-terminal"},
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
