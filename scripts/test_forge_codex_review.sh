#!/usr/bin/env bash
# Test the CODEX review driver's decision logic against a STUBBED gh.
#
# Why stub instead of the real thing: the logic that matters is "review a PR once per
# push, skip it until the head moves". Exercising that against live GitHub would mean
# posting real review comments to real PRs, and would leave the repo's review history
# full of test noise. A stub makes the cases deterministic and lets the awkward ones —
# a reviewer that crashes, a PR that gets a new push — be tested at all.
#
# ⚠️ The stub lives under $STUB_DIR on an EXEC-CAPABLE mount. An earlier version of this
# file put it in /tmp, which is mounted noexec: the stub silently failed with exit 126
# and every test "passed" against the real gh instead. If you move it, check the mount.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DRIVER="$HERE/forge_codex_review.sh"
STUB_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cr-stub.XXXXXX")"
STATE="$(mktemp -u "${TMPDIR:-/tmp}/cr-state.XXXXXX")"
LOG="$(mktemp -u "${TMPDIR:-/tmp}/cr-log.XXXXXX")"
PASS=0; FAIL=0

cleanup() { rm -rf "$STUB_DIR" "$STATE" "$LOG" 2>/dev/null; }
trap cleanup EXIT

ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }

# A fake reviewer: records its invocation, exits with $REVIEWER_RC.
cat > "$STUB_DIR/codex_pr_review.sh" <<EOF
#!/bin/sh
echo "\$@" >> "$LOG"
exit \${REVIEWER_RC:-0}
EOF

# A fake gh: emits $PR_FIXTURE (TSV) for `pr list`.
cat > "$STUB_DIR/gh" <<EOF
#!/bin/sh
if [ "\$1" = "pr" ] && [ "\$2" = "list" ]; then
  [ -n "\${PR_FIXTURE:-}" ] && cat "\$PR_FIXTURE"
  exit \${GH_RC:-0}
fi
exit 0
EOF
chmod +x "$STUB_DIR/gh" "$STUB_DIR/codex_pr_review.sh"

# Run the driver with the stubs shadowing the real tools.
run() {
  PATH="$STUB_DIR:$PATH" NO_COLOR=1 CODEX_REVIEW_STATE="$STATE" \
    CODEX_REVIEW_WRITE_TOKEN=dummy \
    REVIEWER_OVERRIDE=1 \
    bash -c "REVIEWER='$STUB_DIR/codex_pr_review.sh'; source /dev/null; $DRIVER $*" 2>&1
}

# The driver resolves the reviewer relative to itself, so point that at the stub by
# running a copy of the driver beside the stub reviewer.
cp "$DRIVER" "$STUB_DIR/forge_codex_review.sh"
run_stubbed() { PATH="$STUB_DIR:$PATH" NO_COLOR=1 CODEX_REVIEW_STATE="$STATE" \
  CODEX_REVIEW_WRITE_TOKEN=dummy bash "$STUB_DIR/forge_codex_review.sh" "$@" 2>&1; }

printf '  fixture: 2 open PRs\n'

# ── 1. first pass reviews both ───────────────────────────────────────────────────
printf '1001\tshaAAA\tfirst pr\n1002\tshaBBB\tsecond pr\n' > "$STUB_DIR/prs.tsv"
: > "$LOG"; : > "$STATE"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 2 ] && ok "reviews both open PRs on first pass" \
                    || bad "first pass reviewed $calls, expected 2" "$out"
grep -q '^1001 --post$' "$LOG" && ok "passes --post (comment mode), never --approve" \
  || bad "reviewer invoked without --post" "$(cat "$LOG")"
grep -q -- '--approve' "$LOG" && bad "reviewer invoked with --approve" "$(cat "$LOG")" \
                             || ok "never passes --approve"

# ── 2. second pass skips both (unchanged heads) ──────────────────────────────────
: > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 0 ] && ok "skips PRs whose head SHA is unchanged" \
                    || bad "re-reviewed unchanged PRs ($calls calls)" "$out"
grep -q 'unchanged since last review' <<< "$out" && ok "says why it skipped" \
                                              || bad "no skip explanation" "$out"

# ── 3. a new push on one PR triggers exactly one review ──────────────────────────
printf '1001\tshaNEW\tfirst pr\n1002\tshaBBB\tsecond pr\n' > "$STUB_DIR/prs.tsv"
: > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 1 ] && ok "reviews only the PR whose head moved" \
                    || bad "expected 1 review after a new push, got $calls" "$out"
grep -q '^1001 --post$' "$LOG" && ok "reviewed the right PR (1001)" \
                             || bad "wrong PR reviewed" "$(cat "$LOG")"

# ── 4. --force re-reviews unchanged ──────────────────────────────────────────────
: > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed --force)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 2 ] && ok "--force re-reviews unchanged heads" \
                    || bad "--force reviewed $calls, expected 2" "$out"

# ── 5. --limit caps the run ──────────────────────────────────────────────────────
printf '1001\tshaA\tone\n1002\tshaB\ttwo\n1003\tshaC\tthree\n1004\tshaD\tfour\n' > "$STUB_DIR/prs.tsv"
: > "$STATE"; : > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed --limit 2)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 2 ] && ok "--limit caps a run" || bad "--limit reviewed $calls, expected 2" "$out"

# ── 6. --pr targets one PR only ──────────────────────────────────────────────────
: > "$STATE"; : > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed --pr 1003)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 1 ] && grep -q '^1003 --post$' "$LOG" \
  && ok "--pr reviews only that PR" || bad "--pr reviewed $(cat "$LOG")"

# ── 7. a crashed review is NOT recorded as done ──────────────────────────────────
printf '1001\tshaAAA\tfirst pr\n' > "$STUB_DIR/prs.tsv"
: > "$STATE"; : > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" REVIEWER_RC=1 run_stubbed)"
run_stubbed_rc=$?
grep -q 'failed' <<< "$out" && ok "reports a failed review" || bad "failure not reported" "$out"
[ "$run_stubbed_rc" -ne 0 ] && ok "exits non-zero when a review fails" \
                            || bad "exited 0 despite a failed review"
# head still unrecorded => next run retries
: > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 1 ] && ok "retries a previously failed review (not marked done)" \
                    || bad "failed review was recorded as complete — never retried" "$out"

# ── 8. --dry-run touches nothing ─────────────────────────────────────────────────
printf '1001\tshaNEW\tfirst pr\n' > "$STUB_DIR/prs.tsv"
# Clear state first: this asserts --dry-run writes NOTHING, so leftover entries from the
# tests above would fail it for the wrong reason.
: > "$LOG"; : > "$STATE"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed --dry-run)"
[ ! -s "$LOG" ] && ok "--dry-run invokes no reviewer" || bad "--dry-run called the reviewer"
grep -q 'would run' <<< "$out" && ok "--dry-run shows the plan" || bad "no plan shown" "$out"
[ ! -s "$STATE" ] && ok "--dry-run writes no state" || bad "--dry-run wrote state: $(cat "$STATE")"

# ── 9. no token => refuses before listing ────────────────────────────────────────
: > "$LOG"
out="$(PATH="$STUB_DIR:$PATH" NO_COLOR=1 CODEX_REVIEW_STATE="$STATE" \
        PR_FIXTURE="$STUB_DIR/prs.tsv" bash "$STUB_DIR/forge_codex_review.sh" 2>&1)"
rc=$?
[ "$rc" -ne 0 ] && grep -qi 'CODEX_REVIEW_WRITE_TOKEN' <<< "$out" \
  && ok "refuses to post without a write token" || bad "ran without a token" "$out"
[ ! -s "$LOG" ] && ok "unauthenticated run invoked no reviewer" || bad "ran anyway without a token"

# ── 10. gh failure is fatal; empty queue is not ──────────────────────────────────
: > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" GH_RC=7 run_stubbed)"
rc=$?
[ "$rc" -ne 0 ] && ok "gh failure exits non-zero (not silently 'nothing to do')" \
                || bad "gh failure exited 0 — a cron would think it succeeded"
: > "$STUB_DIR/empty.tsv"; : > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/empty.tsv" run_stubbed)"; rc=$?
[ "$rc" -eq 0 ] && ok "empty queue exits 0 (a quiet repo is healthy, not an error)" \
                || bad "empty queue exited $rc — would page on every scheduled run"

# ── 11. --pr is honoured even when the open list is empty ───────────────────────
# Regression (2026-10-04): the empty-queue early-exit ran BEFORE the --pr filter, so
# `--pr N` on a repo with no open PRs printed "no open PRs — nothing to review", exited
# 0, and the queue runner recorded status:"ok" for a review that never happened. Found by
# running the real Repair Bay button path against a just-merged PR.
: > "$STUB_DIR/empty.tsv"; : > "$LOG"; : > "$STATE"
out="$(PR_FIXTURE="$STUB_DIR/empty.tsv" run_stubbed --pr 4242)"
calls=$(wc -l < "$LOG")
[ "$calls" -eq 1 ] && grep -q '^4242 --post$' "$LOG" \
  && ok "--pr reviews the named PR even with no open PRs" \
  || bad "--pr was swallowed by the empty-queue exit ($calls calls)" "$out"
grep -q 'nothing to review' <<< "$out" \
  && bad "still reports 'nothing to review' for a targeted run" \
  || ok "does not claim 'nothing to review' for a targeted run"

# ── 12. ...but a plain sweep with an empty queue still reviews nothing ───────────
: > "$STUB_DIR/empty.tsv"; : > "$LOG"; : > "$STATE"
run_stubbed >/dev/null 2>&1
[ ! -s "$LOG" ] && ok "plain sweep with an empty queue still reviews nothing" \
                 || bad "plain sweep reviewed $(wc -l < "$LOG") PRs with an empty queue"

# ── 13. the count line must not claim "open PR(s)" for a targeted non-open PR ────
# The discriminator used to be a grep for the PR number inside the list, but a
# SYNTHESISED entry is literally that number — so the test always matched and the honest
# "not in the open list" message never printed. An explicit flag fixes it.
printf '1001\tshaA\tone\n' > "$STUB_DIR/prs.tsv"
: > "$STATE"; : > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed --pr 1001)"
grep -q '1 open PR(s)' <<< "$out" \
  && ok "a genuinely open PR still reports the open count" \
  || bad "open PR count lost for a real open PR" "$out"

: > "$STUB_DIR/empty.tsv"; : > "$LOG"; : > "$STATE"
out="$(PR_FIXTURE="$STUB_DIR/empty.tsv" run_stubbed --pr 4242)"
grep -q 'open PR(s)' <<< "$out" \
  && bad "claims 'open PR(s)' for a PR that is not open" "$out" \
  || ok "does not claim 'open PR(s)' for a targeted non-open PR"
grep -q 'not in the open list' <<< "$out" \
  && ok "says the targeted PR is not in the open list" \
  || bad "missing the honest not-in-open-list message" "$out"

# ── 14. the shipped scripts must be executable ──────────────────────────────────
# Both merged as mode 100644 even though they carry shebangs and are documented as
# `scripts/X --once` entry points. A runner invoked that way fails "Permission denied",
# which reads as a broken queue rather than a missing exec bit. Same defect class as
# #3612's driver. git ls-tree is the check: the mode is recorded in the TREE, so this
# catches it regardless of the local filesystem.
REPO_ROOT="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  ok "exec-bit check skipped (not inside a git work tree)"
else
  for f in forge_codex_review.sh codex_review_queue.sh codex_pr_review.sh; do
    mode=$(git -C "$REPO_ROOT" ls-tree HEAD "scripts/$f" | awk '{print $1}')
    [ "$mode" = "100755" ] && ok "scripts/$f is executable in the tree ($mode)" \
                           || bad "scripts/$f merged as $mode — run it via 'bash' or fix the mode"
  done
fi

# ── 15. a targeted PR outside the OPEN list is still reviewed ────────────────────
# Measured live: with #3619 open, `--pr 3618` (merged) reviewed NOTHING while another PR
# was open. #3615 synthesised the entry only for an EMPTY list, so this case slipped
# through — and it first surfaced as {"rc":0,"status":"ok"} for a review that never ran.
printf '1001\tshaA\tone\n1002\tshaB\ttwo\n' > "$STUB_DIR/prs.tsv"
: > "$STATE"; : > "$LOG"
out="$(PR_FIXTURE="$STUB_DIR/prs.tsv" run_stubbed --pr 4242)"; rc=$?
[ "$rc" -eq 0 ] && ok "targeted PR absent from a non-empty list still exits 0" \
                || bad "refused a PR the operator explicitly named" "$out"
[ "$(wc -l < "$LOG")" -eq 1 ] && grep -q '^4242 --post$' "$LOG" \
  && ok "  and reviews exactly that PR" \
  || bad "reviewed $(wc -l < "$LOG") PRs, expected 1: $(cat "$LOG")"
grep -q 'not in the open list' <<< "$out" \
  && ok "  and says it is not in the open list" || bad "no explanation given" "$out"

# The other PRs in the list must NOT be dragged along by the synthesis.
: > "$STATE"; : > "$LOG"
run_stubbed --pr 4242 >/dev/null 2>&1
grep -q '^1001 ' "$LOG" && bad "also reviewed #1001 — synthesis widened the sweep" \
                       || ok "  the open PRs are left alone"

# A targeted PR that IS in the list behaves as before.
: > "$STATE"; : > "$LOG"
run_stubbed --pr 1002 >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && [ "$(wc -l < "$LOG")" -eq 1 ] \
  && ok "a targeted PR that IS in the list still reviews exactly that one" \
  || bad "in-list targeting broke (rc=$rc)"

# An untargeted sweep must NOT synthesise anything.
: > "$STUB_DIR/empty.tsv"; : > "$STATE"; : > "$LOG"
run_stubbed >/dev/null 2>&1; rc=$?
[ "$rc" -eq 0 ] && [ ! -s "$LOG" ] \
  && ok "an untargeted sweep with an empty queue still reviews nothing" \
  || bad "empty-queue sweep changed (rc=$rc)"

printf '\n  %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
