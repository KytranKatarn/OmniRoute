#!/bin/bash
# fix-kbs-pr53-review.sh — correct the false REQUEST CHANGES on kytran-business-suite #53.
#
#   ./fix-kbs-pr53-review.sh              # dry run: prints the plan, changes nothing
#   ./fix-kbs-pr53-review.sh --apply      # post the rebuttal comment ONLY
#   ./fix-kbs-pr53-review.sh --apply --with-port-fix
#                                        # + add the port hardening, commit, push
#
# WHY THIS EXISTS
# ---------------
# kytran-business-suite PR #53 ("feat(store): allow guest checkout to redirect back
# to the consumer site") came back from F.O.R.G.E. with VERDICT: REQUEST CHANGES
# on two findings. Both are wrong:
#
#   1. [CRITICAL] "urlsplit(url) raises ValueError ... unhandled exception".
#      FALSE POSITIVE. `_safe_redirect_url` already wraps it:
#          try:
#              parts = urlsplit(url)
#          except ValueError:
#              return None
#      The finding quotes that exact handler as its own Evidence line. Verified by
#      executing the function: malformed input returns None, no exception escapes.
#
#   2. [INFO] "_ALLOWED_REDIRECT_HOSTS ... could be expanded to include more consumer
#      sites". UNSAFE AS WRITTEN. This is a Stripe payment-redirect allowlist. The
#      code's own comment says "never widen it to accept an arbitrary caller-supplied
#      host", and widening a redirect allowlist is how open-redirect abuse enters a
#      checkout flow. This item must NOT be actioned.
#
# So the correct response to this review is NO code change. "Satisfying" finding 1
# adds a redundant nested try/except; "satisfying" finding 2 widens a payment
# boundary. Posting the rebuttal is the whole fix.
#
# The one GENUINE gap the review missed, offered behind --with-port-fix because it
# is unrelated to the verdict and changes the reviewed head: `urlsplit().hostname`
# excludes the port, and `.port` is never read, so the port is never validated.
# Currently ALLOWED and should be BLOCKED:
#     https://kytranempowerment.com:8443/...   (another service on that host)
#     https://kytranempowerment.com:99999/...  (invalid port, never validated)
#     https://kytranempowerment.com:abc/...    (non-numeric port)
# The fix reads .port INSIDE the existing try (it can itself raise ValueError) and
# requires port in (None, 443), so an explicit :443 keeps working.
#
# SCOPE — read this before running
# --------------------------------
# kytran-business-suite is NOT in the opencode lane's allowed_paths (website/,
# platform_v2/, ai_bridge/, archie-comms/, what-the-fact/, mcp-gateway/, docs/,
# scripts/, config/), and the platform's GitHub write token has no KBS access
# (documented in github_service.py, probed 2026-08-23). This script therefore
# cannot be run by the lane. It is written for an operator (or the Claude CLI lane)
# that already has KBS access. The lane's contribution is the ANALYSIS, which was
# done read-only against the PR diff and by executing the function.
#
# SAFETY
# ------
#   * Dry run unless --apply. Nothing is posted or pushed without it.
#   * FAILS CLOSED if the PR head is not 68f9447af805 — this analysis was pinned to
#     that commit, and a moved head invalidates it.
#   * --with-port-fix touches exactly ONE source file and appends tests; it refuses
#     to run if the working tree is dirty.
#   * Verifies after the fact: re-reads the posted comment, and confirms the push
#     landed, rather than trusting the exit code.
set -uo pipefail

REPO_SLUG="KytranKatarn/kytran-business-suite"
PR=53
EXPECTED_HEAD="68f9447af805"
BRANCH="fix/store-checkout-redirect-urls"
KBS_DIR="${KBS_DIR:-/mnt/archie_brain/kytran-business-suite}"
SRC="plugins/kbs_store/public_routes.py"
TEST="plugins/kbs_store/tests/test_store.py"

APPLY=0
PORT_FIX=0
FAILED=0

for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --with-port-fix) PORT_FIX=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; }
die()  { printf '  FAIL  %s\n' "$*" >&2; FAILED=$((FAILED+1)); }

REBUTTAL_BODY='F.O.R.G.E. review re-checked against the diff — both findings are unfounded, and the requested changes should **not** be applied.

**1. `[CRITICAL] urlsplit(url) raises ValueError` — false positive.**

`_safe_redirect_url` already handles it:

```python
try:
    parts = urlsplit(url)
except ValueError:
    return None
```

The finding quotes that handler as its own `Evidence:` line, so the code it points at is the code that already fixes it. Executing the function against malformed input (`https://[::1/x`) returns `None` with no exception escaping.

**2. `[INFO] _ALLOWED_REDIRECT_HOSTS could be expanded` — unsafe as written, do not action.**

This is a Stripe **payment-redirect** allowlist. The function'"'"'s own comment states: *"never widen it to accept an arbitrary caller-supplied host."* Expanding it is how open-redirect abuse enters a checkout flow. Recommendation: leave the allowlist exactly as it is.

**Verified behaviour of the current guard** (function executed against each input):

| input | result |
|---|---|
| `https://kytranempowerment.com/thanks` | ALLOW (intended) |
| `https://kytranempowerment.com.evil.com/x` | BLOCK |
| `https://kytranempowerment.com@evil.com/x` | BLOCK |
| `http://kytranempowerment.com/x` | BLOCK |
| `https://evil.com/?r=kytranempowerment.com` | BLOCK |
| `https://shop.kytranempowerment.com/x` | BLOCK |
| `https://kytranempowerment.com./x` | BLOCK |
| `https://[::1/x` | BLOCK, no exception |

**Recommendation: no code change; please re-review.**

One genuine gap the review did not flag, tracked separately because it is unrelated to the verdict: `urlsplit().hostname` excludes the port and `.port` is never read, so the port is never validated — `https://kytranempowerment.com:8443/...`, `:99999` and `:abc` are all currently accepted. Low severity (same host), worth a follow-up.'

say "=============================================================="
say " kytran-business-suite #$PR — review correction"
say "=============================================================="

# ── preflight ───────────────────────────────────────────────────────────────
[ -d "$KBS_DIR/.git" ] || { die "no KBS checkout at $KBS_DIR (set KBS_DIR=...)"; exit 1; }
ok "checkout: $KBS_DIR"

cd "$KBS_DIR" || exit 1
# Only TRACKED changes block. Untracked files (there are 3 unrelated ones under
# kytran-auth-pkg/ right now, someone else's in-progress work) must not block a
# comment post, and staging by explicit path means they are never picked up by a
# commit. A blanket "clean tree" check was wrong here and would have blocked the
# operator for no reason.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  git status --porcelain --untracked-files=no | sed 's/^/        /' >&2
  die "tracked files are modified — commit or stash first (untracked files are fine)"
  exit 1
fi
ok "no tracked modifications (untracked files left alone)"
UNTRACKED=$(git status --porcelain | grep -c '^??' || true)
[ "$UNTRACKED" -gt 0 ] && say "      note: $UNTRACKED untracked path(s) present and untouched"

if ! git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
  git fetch -q origin "$BRANCH" || { die "could not fetch $BRANCH"; exit 1; }
fi
HEAD_SHA=$(git rev-parse "origin/$BRANCH")
HEAD_SHORT=${HEAD_SHA:0:12}
if [ "$HEAD_SHORT" != "$EXPECTED_HEAD" ]; then
  die "PR head is $HEAD_SHORT, analysis was pinned to $EXPECTED_HEAD."
  die "The diff changed since this analysis — re-verify before posting anything."
  exit 1
fi
ok "head matches the analysed commit ($HEAD_SHORT)"

# ── auth ─────────────────────────────────────────────────────────────────────
HAVE_GH=0
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  HAVE_GH=1; ok "auth: gh CLI"
elif [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
  ok "auth: \$GH_TOKEN/\$GITHUB_TOKEN from environment"
else
  die "no GitHub auth (need an authed gh CLI, or GH_TOKEN/GITHUB_TOKEN in env)"
  say "       The opencode lane's platform token has NO KBS access, which is why"
  say "       this has to run somewhere else."
  exit 1
fi

# ── plan ─────────────────────────────────────────────────────────────────────
say ""
say "Plan:"
say "  1. post a technical rebuttal on #$PR (no code change)"
if [ "$PORT_FIX" -eq 1 ]; then
  say "  2. add the port hardening to $SRC + tests, commit, push to $BRANCH"
else
  say "  2. (skipped — pass --with-port-fix to also close the port gap)"
fi

if [ "$APPLY" -eq 0 ]; then
  say ""
  say "DRY RUN — nothing posted, nothing pushed. Re-run with --apply."
  say ""
  say "---- rebuttal that would be posted ----"
  printf '%s\n' "$REBUTTAL_BODY"
  exit 0
fi

# ── 1. post the rebuttal ─────────────────────────────────────────────────────
say ""
say "[1/2] Posting the rebuttal"
BODY_FILE=$(mktemp)
printf '%s\n' "$REBUTTAL_BODY" > "$BODY_FILE"

# IDEMPOTENCY — added after a real run posted the same rebuttal twice, because
# the comment was posted unconditionally on every --apply. An operator running
# `--apply` and then `--apply --with-port-fix` is the obvious sequence, so this
# is not a contrived case. Match on a stable prefix of the body: if the rebuttal
# is already on the PR, say so and skip rather than duplicate it.
SENTINEL="F.O.R.G.E. review re-checked against the diff"
EXISTING=""
if [ "$HAVE_GH" -eq 1 ]; then
  EXISTING=$(gh api "repos/$REPO_SLUG/issues/$PR/comments" --jq \
    '[.[] | select(.body | startswith("'"$SENTINEL"'"))] | length' 2>/dev/null || echo "")
else
  EXISTING=$(curl -sS \
    -H "Authorization: Bearer ${GH_TOKEN:-$GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO_SLUG/issues/$PR/comments" 2>/dev/null \
    | python3 -c '
import json,sys
try: cs = json.load(sys.stdin)
except Exception: cs = []
print(len([c for c in cs if str(c.get("body","")).startswith(sys.argv[1])]))
' "$SENTINEL" 2>/dev/null || echo "")
fi

if [ -n "$EXISTING" ] && [ "$EXISTING" -gt 0 ] 2>/dev/null; then
  ok "rebuttal already present ($EXISTING matching comment(s)) — NOT posting again"
  say "      delete a duplicate with:"
  say "        gh api -X DELETE repos/$REPO_SLUG/issues/$PR/comments/<id>"
else

if [ "$HAVE_GH" -eq 1 ]; then
  if gh pr comment "$PR" --repo "$REPO_SLUG" --body-file "$BODY_FILE" >/dev/null 2>&1; then
    ok "comment posted via gh"
  else
    die "gh pr comment failed"
  fi
else
  CODE=$(curl -sS -o /tmp/kbs53_resp.json -w '%{http_code}' \
    -X POST \
    -H "Authorization: Bearer ${GH_TOKEN:-$GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/$REPO_SLUG/issues/$PR/comments" \
    --data-binary @<(python3 -c '
import json,sys
print(json.dumps({"body": open(sys.argv[1]).read()}))
' "$BODY_FILE") 2>/dev/null)
  case "$CODE" in
    201|200) ok "comment posted (HTTP $CODE)" ;;
    *) die "comment POST failed (HTTP $CODE): $(head -c 200 /tmp/kbs53_resp.json 2>/dev/null)" ;;
  esac
fi
fi

# verify it actually landed rather than trusting the exit code
if [ "$HAVE_GH" -eq 1 ]; then
  N=$(gh pr view "$PR" --repo "$REPO_SLUG" --json comments --jq '.comments | length' 2>/dev/null || echo 0)
  say "      comment count now: $N"
fi
rm -f "$BODY_FILE"

# ── 2. optional port fix ─────────────────────────────────────────────────────
if [ "$PORT_FIX" -eq 1 ]; then
  say ""
  say "[2/2] Port hardening"
  git checkout -q -B "$BRANCH" "origin/$BRANCH" || { die "could not check out $BRANCH"; exit 1; }

  python3 - "$SRC" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = """    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.hostname not in _ALLOWED_REDIRECT_HOSTS:"""
new = """    try:
        parts = urlsplit(url)
        # .port is read INSIDE the try: it raises ValueError on a non-numeric or
        # out-of-range port. hostname excludes the port, so without this a
        # redirect to an arbitrary port on an allowlisted host would pass.
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme != "https"
            or parts.hostname not in _ALLOWED_REDIRECT_HOSTS
            or port not in (None, 443)):"""
if old not in s:
    print("ANCHOR NOT FOUND — the function changed since this analysis. Refusing.")
    sys.exit(1)
open(p, "w").write(s.replace(old, new, 1))
print("patched", p)
PY
  [ $? -eq 0 ] || { die "port fix did not apply (anchor moved) — nothing committed"; exit 1; }
  ok "source patched"

  cat >> "$TEST" <<'PYEOF'


class TestSafeRedirectUrlPort:
    """`.port` must be validated: hostname excludes it, so a non-standard or
    malformed port on an allowlisted host is currently accepted."""

    def _fn(self):
        from plugins.kbs_store.public_routes import _safe_redirect_url
        return _safe_redirect_url

    def test_allows_explicit_443(self):
        f = self._fn()
        assert f("https://kytranempowerment.com:443/x") is not None

    def test_allows_default_port(self):
        f = self._fn()
        assert f("https://kytranempowerment.com/x") is not None

    def test_blocks_non_standard_port(self):
        f = self._fn()
        assert f("https://kytranempowerment.com:8443/x") is None

    def test_blocks_out_of_range_port(self):
        f = self._fn()
        assert f("https://kytranempowerment.com:99999/x") is None

    def test_blocks_non_numeric_port(self):
        f = self._fn()
        assert f("https://kytranempowerment.com:abc/x") is None
PYEOF
  ok "tests appended"

  git add "$SRC" "$TEST"
  say "      staged:"; git diff --cached --name-only | sed 's/^/        /'
  git commit -q -m "$(cat <<'EOF'
fix(store): validate the redirect port, not just the host

`urlsplit().hostname` excludes the port and `.port` was never read, so the
port was never validated. An allowlisted host with a non-standard,
out-of-range, or non-numeric port was accepted and handed to Stripe:

    https://kytranempowerment.com:8443/...   another service on that host
    https://kytranempowerment.com:99999/...  invalid port
    https://kytranempowerment.com:abc/...    non-numeric port

Read `.port` inside the existing try (it can itself raise ValueError) and
require it to be None or 443, so an explicit :443 keeps working.

Unrelated to the F.O.R.G.E. REQUEST CHANGES verdict on this PR, which was
a false positive — see the PR comment. This closes a gap that review missed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)" && ok "committed $(git rev-parse --short HEAD)"

  if git push -q origin "$BRANCH" 2>&1; then
    ok "pushed to origin/$BRANCH"
  else
    die "push FAILED — commit is local only, resolve credentials and re-run"
  fi
  say "      remote head is now $(git ls-remote origin "$BRANCH" | cut -c1-12)"
else
  say ""
  say "[2/2] Port fix skipped. Nothing was changed in the codebase."
fi

say ""
say "--------------------------------------------------------------"
if [ "$FAILED" -eq 0 ]; then
  say "Done. #$PR now carries a rebuttal explaining the false verdict."
  say "Still needed: a human merges (lane rule: never merge), and the"
  say "REQUEST CHANGES row needs clearing so the governance gate passes."
else
  say "Completed with $FAILED problem(s) — see FAIL lines above."
fi
say "--------------------------------------------------------------"
[ "$FAILED" -eq 0 ] || exit 1
