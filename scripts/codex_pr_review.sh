#!/usr/bin/env bash
# codex_pr_review.sh — run a Codex code review of a GitHub PR
#
# WHAT THIS IS
#   F.O.R.G.E. writes verdicts to the `pr_reviews` table and never reaches
#   GitHub, so GitHub-only agents (Claude) cannot see them. This closes that
#   gap: it fetches the PR diff, has Codex review it, and posts the result to
#   GitHub as a COMMENT so a human still decides.
#
#   Posting as COMMENT, not APPROVE. main requires 1 approving review; if Codex
#   emitted APPROVE it would satisfy that and auto-unblock merges. COMMENT is
#   advisory and reversible. Promote deliberately, not by default.
#
# IDENTITY — READ THIS BEFORE USING --post
#   Reading the PR needs only a read token. POSTING needs a WRITE token, and the
#   platform's write token belongs to KytranKatarn — the SAME account that authors
#   these PRs. GitHub rejects a self-approval, so a review posted that way can be a
#   COMMENT but will NOT satisfy branch protection. That is a platform rule, not a
#   bug, and it is why the default here is no-post.
#
#   To ever post an APPROVE you need a distinct bot account (or GitHub App
#   installation) whose login differs from the PR author. Supply it as
#   CODEX_REVIEW_WRITE_TOKEN.
#
#   FORGE_REVIEW_TOKEN is deliberately least-privilege READ-ONLY
#   (repair_bay/services/github_service.py:41-47). It cannot post. Don't try.
#
# SANDBOX — READ THIS
#   Codex runs with --dangerously-bypass-approvals-and-sandbox. That is forced,
#   not chosen: this container blocks user namespaces, so bubblewrap cannot
#   start (verified: `unshare -Ur` fails on /proc/self/uid_map).
#
#   That flag also skips approval prompts, so Codex holds this container's
#   privileges. The containment is the DISPOSABLE WORKTREE below plus a
#   read-only prompt contract -- NOT the sandbox. Never point this at a
#   trusted-but-unreviewed branch and leave the result unattended.
#
# USAGE
#   scripts/codex_pr_review.sh <pr-number>              # show the review, post nothing
#   scripts/codex_pr_review.sh <pr-number> --post       # also post as COMMENT
#   scripts/codex_pr_review.sh <pr-number> --approve    # post as APPROVE (grants merge power)
#   scripts/codex_pr_review.sh <pr-number> --diff-only  # just show what would be reviewed
#
# EXAMPLES
#   scripts/codex_pr_review.sh 3598                 # review, don't post
#   scripts/codex_pr_review.sh 3598 --post          # review + post COMMENT

set -uo pipefail

REPO="KytranKatarn/archie-platform"
MAX_DIFF_CHARS="${MAX_DIFF_CHARS:-60000}"

PR=""
POST_MODE="none"     # none | comment | approve
DIFF_ONLY=0
SELF_TEST=0

for arg in "$@"; do
  case "$arg" in
    --post)      POST_MODE="comment"  ;;
    --approve)   POST_MODE="approve"   ;;
    --diff-only) DIFF_ONLY=1           ;;
    --self-test) SELF_TEST=1            ;;
    -h|--help)   sed -n '2,40p' "$0"; exit 0 ;;
    -*)          echo "unknown flag: $arg" >&2; exit 2 ;;
    *)           PR="$arg"            ;;
  esac
done

# Canaries: planted bugs that MUST be reported. The first version of this
# script's prompt returned "APPROVE / no concrete correctness bugs" on these --
# the line "an empty review is a valid review" biased it toward a null answer.
# Re-run after ANY prompt change; a PASS here means the reviewer still bites.
CANARY_DIFF='--- a/src/users.py
+++ b/src/users.py
@@ -40,3 +40,7 @@
 def find_user(users, email):
-    return next(u for u in users if u.email == email)
+    return next(u for u in users if u.email == email)
+def delete_user(users, uid):
+    for i, u in enumerate(users):
+        if u.id == uid:
+            users.pop(i)
'

if [ "$SELF_TEST" = "1" ]; then
  echo "codex review self-test — planted pop()-during-enumerate() bug must be reported"
  R=$(cd /tmp && timeout 900 codex exec --dangerously-bypass-approvals-and-sandbox \
      -c model_provider="openai" \
      "Review this pull request for bugs. The unified diff is below.

For each change, ask: what input makes this behave incorrectly?

Skip formatting and naming. Report every real bug.

Answer as:
  VERDICT: <APPROVE | REQUEST_CHANGES | COMMENT>
  - [severity] file:line - what breaks, and the input that triggers it

DIFF:
$CANARY_DIFF" 2>&1)
  printf '%s\n' "$R" | grep -oE "^VERDICT: [A-Z_]+" | head -1
  if printf '%s' "$R" | grep -qiE "enumerate|adjacent|skips? "; then
    echo "PASS: reviewer bites (bug reported)"
    exit 0
  fi
  echo "FAIL: reviewer went silent on a planted bug -- the prompt is too permissive."
  echo "This is the exact failure that shipped once already."
  exit 1
fi

if [ -z "$PR" ]; then
  echo "usage: scripts/codex_pr_review.sh <pr-number> [--post|--approve|--diff-only]" >&2
  exit 2
fi

# ---------------------------------------------------------------- token
READ_TOKEN="${CODEX_REVIEW_TOKEN:-}"
if [ -z "$READ_TOKEN" ]; then
  # Read FORGE_REVIEW_TOKEN from the running platform without printing it.
  READ_TOKEN=$(docker exec archie_platform sh -c 'printf %s "$FORGE_REVIEW_TOKEN"' 2>/dev/null)
fi
if [ -z "$READ_TOKEN" ]; then
  echo "FATAL: no read token. Set CODEX_REVIEW_TOKEN, or make sure FORGE_REVIEW_TOKEN" >&2
  echo "       is set on archie_platform." >&2
  exit 1
fi

# Posting needs a WRITE token. The platform write token shares the PR author's
# login, so GitHub will treat it as a self-review and refuse to APPROVE.
WRITE_TOKEN="${CODEX_REVIEW_WRITE_TOKEN:-}"
if [ -z "$WRITE_TOKEN" ]; then
  WRITE_TOKEN=$(docker exec archie_platform sh -c 'cat /mnt/archie_brain/secrets/api/github_token.txt 2>/dev/null' || true)
fi
if [ -z "$WRITE_TOKEN" ]; then
  WRITE_TOKEN=$(docker exec -i archie_platform sh -c 'printf %s "$GITHUB_TOKEN"' 2>/dev/null)
fi
if [ "$WRITE_TOKEN" = "$READ_TOKEN" ]; then
  WRITE_TOKEN=""   # read-only PAT; posting would fail
fi

export GH_TOKEN="$READ_TOKEN"

# ---------------------------------------------------------------- metadata
gh_json() { gh api "$@" 2>/dev/null; }

META=$(gh_json "repos/$REPO/pulls/$PR" \
  --jq '{title:.title, author:.user.login, state:.state, head:.head.ref, sha:.head.sha, base:.base.ref, files:.changed_files, additions:.additions, deletions:.deletions}')
if [ -z "$META" ]; then
  echo "FATAL: could not read PR #$PR from $REPO (check the token has repo scope)" >&2
  exit 1
fi

TITLE=$(printf '%s' "$META" | python3 -c 'import sys,json;print(json.load(sys.stdin)["title"])')
AUTHOR=$(printf '%s' "$META" | python3 -c 'import sys,json;print(json.load(sys.stdin)["author"])')
HEADREF=$(printf '%s' "$META" | python3 -c 'import sys,json;print(json.load(sys.stdin)["head"])')
STATE=$(printf '%s' "$META" | python3 -c 'import sys,json;print(json.load(sys.stdin)["state"])')
STATS=$(printf '%s' "$META" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("%s files, +%s/-%s"%(d["files"],d["additions"],d["deletions"]))')

echo "PR #$PR  [$STATE]"
echo "  title : $TITLE"
echo "  author: $AUTHOR"
echo "  change: $STATS"
echo

if [ "$STATE" != "open" ]; then
  echo "note: PR is $STATE, not open."
fi

# ---------------------------------------------------------------- diff
WORKTREE=""
cleanup() {
  if [ -n "$WORKTREE" ] && [ -d "$WORKTREE" ]; then
    git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
    rm -rf "$WORKTREE" 2>/dev/null || true
  fi
}
trap cleanup EXIT

WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/codex-review-$PR-XXXXXX")
git -C "$REPO" fetch -q origin "pull/$PR/head:refs/codex-review/$PR" 2>/dev/null
git -C "$REPO" worktree add --detach "$WORKTREE" "refs/codex-review/$PR" >/dev/null 2>&1
if [ ! -d "$WORKTREE" ]; then
  echo "FATAL: could not create disposable worktree" >&2
  exit 1
fi

DIFF_FILE=$(mktemp)
git -C "$WORKTREE" diff --no-color "origin/${HEADREF}...HEAD" > "$DIFF_FILE" 2>/dev/null || true
# Fall back to the GitHub-provided diff — works even for cross-repo PRs.
if [ ! -s "$DIFF_FILE" ]; then
  gh api "repos/$REPO/pulls/$PR/files" --jq '.[] | "--- \(.filename)\n@@ \(.patch // "(binary or too large)")"' > "$DIFF_FILE" 2>/dev/null || true
fi

DIFF_SIZE=$(wc -c < "$DIFF_FILE" | tr -d ' ')
echo "  diff  : ${DIFF_SIZE} bytes"
if [ "$DIFF_SIZE" -gt "$MAX_DIFF_CHARS" ]; then
  head -c "$MAX_DIFF_CHARS" "$DIFF_FILE" > "$DIFF_FILE.trunc" && mv "$DIFF_FILE.trunc" "$DIFF_FILE"
  echo "  diff  : TRUNCATED to $MAX_DIFF_CHARS chars"
fi

if [ "$DIFF_ONLY" = "1" ]; then
  echo
  cat "$DIFF_FILE"
  rm -f "$DIFF_FILE"
  exit 0
fi

if [ "$DIFF_SIZE" -eq 0 ]; then
  echo "FATAL: empty diff — nothing to review." >&2
  rm -f "$DIFF_FILE"
  exit 1
fi

# ---------------------------------------------------------------- review
PROMPT=$(python3 - "$TITLE" "$DIFF_FILE" <<'PY'
import sys
title, diff_path = sys.argv[1], sys.argv[2]
diff = open(diff_path, encoding="utf-8", errors="replace").read()
print(f"""Review this pull request for bugs. Title: "{title}"

Below is the unified diff (base -> head).

For each change, ask: what input makes this behave incorrectly? Trace loops,
index arithmetic, None/empty handling, and missing keys concretely.

Skip: formatting, naming, import order, type hints, and "add tests" suggestions.

Answer in this shape:
  VERDICT: <APPROVE | REQUEST_CHANGES | COMMENT>
  <one-line summary>
  - [high|medium|low] file:line - what breaks, and the input that triggers it

Work the diff line by line before answering. Report every real bug you find.

Read-only: do not write files, run git, or call the network.

DIFF:
{diff}
""")
PY
)

echo "  invoking codex (unsandboxed — container blocks user namespaces)..."
REVIEW=$(cd "$WORKTREE" && timeout 900 codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  -c model_provider="openai" \
  "$PROMPT" 2>&1)

# Strip codex's own chatter; keep the verdict block.
BODY=$(printf '%s\n' "$REVIEW" \
  | awk '/^VERDICT:/{f=1} f' \
  | sed '/^tokens used$/,$d' \
  | sed 's/[[:space:]]*$//' \
  | grep -v '^$')

rm -f "$DIFF_FILE"

if [ -z "$BODY" ]; then
  echo
  echo "FATAL: codex produced no review. Raw output:" >&2
  printf '%s\n' "$REVIEW" | head -30 >&2
  exit 1
fi

echo
echo "================ CODEX REVIEW ================"
printf '%s\n' "$BODY"
echo "=============================================="

# Never let a model-supplied VERDICT silently escalate to an approving review.
# --approve is the only path to APPROVE, and it is explicit in the command line.
if [ "$POST_MODE" != "none" ]; then
  STATE_ARG="COMMENT"
  if [ "$POST_MODE" = "approve" ]; then
    STATE_ARG="APPROVE"
  fi

  if [ -z "$WRITE_TOKEN" ]; then
    echo "FATAL: no write token available. Set CODEX_REVIEW_WRITE_TOKEN to a bot" >&2
    echo "       account whose login differs from the PR author, or add one." >&2
    echo "       (The platform's own write token shares the PR author's login, so" >&2
    echo "        GitHub would refuse the review as a self-review.)" >&2
    exit 1
  fi
  export GH_TOKEN="$WRITE_TOKEN"
  # Confirm the identity that will post.
  WHO=$(gh api user --jq .login 2>/dev/null)
  echo
  echo "posting to GitHub as: $WHO"

  if printf '%s' "$BODY" | head -1 | grep -qE '^VERDICT:\s*REQUEST_CHANGES'; then
    if [ "$POST_MODE" = "approve" ]; then
      echo "note: verdict is REQUEST_CHANGES; posting as REQUEST_CHANGES instead of APPROVE."
      STATE_ARG="REQUEST_CHANGES"
    fi
  fi

  printf '%s' "$BODY" | gh pr review "$PR" --repo "$REPO" --request-changes --body-file - >/dev/null 2>&1 \
    || printf '%s' "$BODY" | gh pr review "$PR" --repo "$REPO" --comment --body-file - >/dev/null 2>&1

  if [ $? -eq 0 ]; then
    echo "posted: https://github.com/$REPO/pull/$PR"
  else
    echo "WARNING: post failed — review above was NOT sent to GitHub." >&2
  fi
else
  echo
  echo "not posted. Re-run with --post to add as COMMENT, or --approve to grant merge power."
fi
