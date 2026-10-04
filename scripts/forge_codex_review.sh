#!/usr/bin/env bash
# forge_codex_review.sh — run CODEX reviews across open PRs, at volume.
#
# WHY (2026-10-03): CodeRabbit reviews 1 PR/hour. This platform ships more than that,
# so most PRs reach a human unreviewed. codex_pr_review.sh already does a competent
# whole-diff review, but nothing calls it: it takes ONE PR number per invocation. This
# is the missing driver — enumerate open PRs and feed them to it.
#
# WHAT IT DELIBERATELY DOES NOT DO
#   * It never approves. `--post` only, never `--approve`. An APPROVE from the same
#     model family that wrote the code is not review, and it would satisfy branch
#     protection and auto-unblock merges. Findings land as COMMENTs; a human merges.
#   * It never merges.
#   * It never re-reviews an unchanged head. That is the whole cost-control mechanism:
#     state is keyed on (PR, head SHA), so a PR is reviewed once per push, not once
#     per cron tick. Re-reviewing is available via --force when you want it.
#
# IDENTITY: posting needs a write token. The platform's own token belongs to
# KytranKatarn, which is also the PR author — GitHub refuses self-APPROVAL but happily
# accepts a self-COMMENT, so COMMENT mode needs no second account. This is the reason
# this driver is comment-only by design and not a missing feature.
#
# Usage:
#   scripts/forge_codex_review.sh                 # review open PRs needing it
#   scripts/forge_codex_review.sh --dry-run       # show the plan, review nothing
#   scripts/forge_codex_review.sh --pr 3611       # one PR (still respects state)
#   scripts/forge_codex_review.sh --force          # re-review even if head unchanged
#   scripts/forge_codex_review.sh --limit 5        # cap this run
#
# Environment:
#   REPO                    owner/name            (default KytranKatarn/archie-platform)
#   CODEX_REVIEW_WRITE_TOKEN write token for posting (required unless --dry-run)
#   CODEX_REVIEW_STATE      state file            (default ~/.local/state/archie-codex-reviews.tsv)
#   REVIEW_TIMEOUT          seconds per review    (default 900)
#   NO_COLOR=1              plain output

set -uo pipefail

REPO="${REPO:-KytranKatarn/archie-platform}"
STATE_FILE="${CODEX_REVIEW_STATE:-$HOME/.local/state/archie-codex-reviews.tsv}"
REVIEW_TIMEOUT="${REVIEW_TIMEOUT:-900}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REVIEWER="$SCRIPT_DIR/codex_pr_review.sh"

DRY_RUN=0
TARGETED_NOT_OPEN=0
FORCE=0
ONLY_PR=""
LIMIT=0

# Parse with a while/ shift, NOT `for arg in "$@"`. A `for` over "$@" expands the list
# once, so the `shift` inside `--limit)` did not stop the loop from also delivering the
# number it had just consumed — `--limit 2` therefore set the PR filter to "2" and
# matched nothing. Caught by test 5, which expected 2 reviews and got 0.
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force)   FORCE=1; shift ;;
    --pr)      ONLY_PR="${2:-}"; [ $# -ge 2 ] && shift 2 || shift ;;
    --limit)   LIMIT="${2:-0}"; [ $# -ge 2 ] && shift 2 || shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    -*)        echo "unknown flag: $1" >&2; exit 2 ;;
    *)         ONLY_PR="$1"; shift ;;
  esac
done

c_red()   { [ -n "${NO_COLOR:-}" ] && printf '%s\n' "$1" || printf '\033[31m%s\033[0m\n' "$1"; }
c_dim()   { [ -n "${NO_COLOR:-}" ] && printf '%s\n' "$1" || printf '\033[2m%s\033[0m\n' "$1"; }
c_ok()    { [ -n "${NO_COLOR:-}" ] && printf '%s\n' "$1" || printf '\033[32m%s\033[0m\n' "$1"; }
die()     { c_red "FATAL: $*" >&2; exit 1; }

[ -x "$REVIEWER" ] || [ -f "$REVIEWER" ] || die "reviewer not found: $REVIEWER"
[ "$REVIEWER" != "$0" ] || die "reviewer path resolved to this script — refusing to recurse"

command -v gh >/dev/null || die "gh not on PATH"

# ── state ────────────────────────────────────────────────────────────────────────
# TSV: pr_number <TAB> head_sha <TAB> reviewed_at <TAB> outcome
mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
touch "$STATE_FILE" 2>/dev/null || true

last_sha_for() {  # $1 = pr number -> prints the head sha last reviewed, or empty
  awk -F'\t' -v pr="$1" '$1 == pr { sha = $2 } END { print sha }' "$STATE_FILE" 2>/dev/null
}

record() {  # $1=pr $2=sha $3=outcome
  local tmp
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")" || return 1
  awk -F'\t' -v pr="$1" 'BEGIN{OFS="\t"} $1 != pr' "$STATE_FILE" > "$tmp" 2>/dev/null
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" >> "$tmp"
  mv "$tmp" "$STATE_FILE"
}

# ── discovery ────────────────────────────────────────────────────────────────────
# Only PRs the token can actually see, and only ones that need a review.
# Distinguishes "gh failed" from "nothing is open" — they are not the same event, and
# conflating them made an empty queue look like a fatal error to whatever runs this.
list_prs() {
  gh pr list --repo "$REPO" --state open --limit 100 \
    --json number,headRefOid,title --jq '.[] | "\(.number)\t\(.headRefOid)\t\(.title)"'
}

printf '%s\n' "==> CODEX review driver — repo $REPO"
c_dim "    state: $STATE_FILE"
[ "$DRY_RUN" -eq 1 ] && c_dim "    DRY RUN — nothing will be reviewed or posted"

if [ "$DRY_RUN" -ne 1 ] && [ -z "${CODEX_REVIEW_WRITE_TOKEN:-}" ]; then
  die "CODEX_REVIEW_WRITE_TOKEN is unset. Posting needs a write token.
     Any write token works for COMMENT mode — the PR author's own token is fine,
     because only self-APPROVAL is refused by GitHub.
     Use --dry-run to rehearse the plan without one."
fi

if ! PR_LIST="$(list_prs)"; then
  die "gh could not list open PRs in $REPO (auth, network, or repo name?). Nothing was run."
fi

# An EMPTY open list is only "nothing to do" when we were asked to sweep the queue.
  # With --pr N the caller named the target explicitly, and it must be honoured even when
  # that PR is not in the open list — a just-merged PR, or one reviewed the moment after
  # it closed. Short-circuiting here made `--pr 999999` print "no open PRs — nothing to
  # review", exit 0, and the queue runner record status:"ok" for a review that never
  # ran. A silent success is worse than a failure; the Repair Bay button reports on it.
  if [ -z "$PR_LIST" ] && [ -z "$ONLY_PR" ]; then
    # A quiet queue is the normal state of a healthy repo, not an error. Exiting non-zero
    # here would make every scheduled run look like a failure.
    printf '    no open PRs — nothing to review\n'
    printf '==> 0 reviewed, 0 unchanged-skipped, 0 failed\n'
    exit 0
  fi

  if [ -z "$PR_LIST" ]; then
    # Targeted run with an empty open list: synthesise a single-entry list so the loop
    # below reviews exactly what was asked for. The head SHA is unknown here, which
    # disables the unchanged-skip check for this one run — correct, because we have not
    # seen this head before.
    printf '    no open PRs — reviewing PR #%s directly\n' "$ONLY_PR"
    TARGETED_NOT_OPEN=1
    PR_LIST="$ONLY_PR"$'\t''(targeted)'
  fi

OPEN_COUNT=$(printf '%s\n' "$PR_LIST" | grep -c . || true)
  # A synthesised entry MATCHES the old grep test (it is literally the PR number in
  # the list), so that test could never tell 'targeted and not open' from 'open'. Use an
  # explicit flag instead.
  if [ "$TARGETED_NOT_OPEN" -eq 1 ]; then
    # The targeted PR was not in the open list — it is merged or otherwise closed.
    # Printing "1 open PR(s)" here would be a small lie about what was reviewed.
    printf '    reviewing PR #%s directly (not in the open list)\n' "$ONLY_PR"
  else
    printf '    %s open PR(s)\n' "$OPEN_COUNT"
  fi

reviewed=0; skipped=0; failed=0
printf '\n'

while IFS=$'\t' read -r pr sha title; do
  [ -n "${pr:-}" ] || continue

  if [ -n "$ONLY_PR" ] && [ "$pr" != "$ONLY_PR" ]; then continue; fi
  if [ "$LIMIT" -gt 0 ] && [ "$reviewed" -ge "$LIMIT" ]; then break; fi

  prev="$(last_sha_for "$pr")"
  if [ "$FORCE" -ne 1 ] && [ -n "$prev" ] && [ "$prev" = "$sha" ]; then
    printf '  #%-5s %s\n' "$pr" "$(c_dim 'unchanged since last review — skipping')"
    skipped=$((skipped + 1))
    continue
  fi

  printf '  #%-5s %s\n' "$pr" "${title:0:64}"
  [ "$FORCE" -eq 1 ] && [ -n "$prev" ] && c_dim "    --force: re-reviewing unchanged head"

  if [ "$DRY_RUN" -eq 1 ]; then
    printf '    %s\n' "$(c_dim "would run: codex_pr_review.sh $pr --post  (timeout ${REVIEW_TIMEOUT}s)")"
    reviewed=$((reviewed + 1))
    continue
  fi

  if timeout "$REVIEW_TIMEOUT" "$REVIEWER" "$pr" --post; then
    record "$pr" "$sha" "posted"
    printf '    %s\n' "$(c_ok 'review posted')"
    reviewed=$((reviewed + 1))
  else
    rc=$?
    # Deliberately NOT recorded. Recording the head here would make a crashed review
    # look done and the PR would never be retried — the failure would be silent and
    # permanent, which is the worst shape this script could have. An earlier version
    # did record it and its own log line claimed it would retry; test 7 caught the lie.
    printf '    %s\n' "$(c_red "review FAILED (rc=$rc) — not recorded, will retry next run")"
    failed=$((failed + 1))
  fi
done <<< "$PR_LIST"

printf '\n==> %s reviewed, %s unchanged-skipped, %s failed\n' "$reviewed" "$skipped" "$failed"
printf '    Findings land as PR comments. They do NOT satisfy branch protection and\n'
printf '    do NOT unblock a merge — a human still reads them and still merges.\n'

[ "$failed" -gt 0 ] && exit 1
exit 0
