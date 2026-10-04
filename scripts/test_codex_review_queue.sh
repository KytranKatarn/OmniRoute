#!/usr/bin/env bash
# Test the host-side queue runner against a STUBBED driver and a temp spool.
#
# The runner is the half that actually executes something, and the PR number it reads
# out of a JSON file is the one value that ends up on a command line. So the cases that
# matter most are the hostile ones: a request whose "kind" is wrong, a PR that is not a
# bare number, and a request that tries to smuggle shell metacharacters through.
#
# A stub driver keeps this off real PRs — the real one posts GitHub comments.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$HERE/codex_review_queue.sh"
STUB_DIR="$(mktemp -d "${TMPDIR:-/tmp}/crq.XXXXXX")"
LOG="$STUB_DIR/driver.log"
PASS=0; FAIL=0
cleanup() { rm -rf "$STUB_DIR" 2>/dev/null; }
trap cleanup EXIT

ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }

cat > "$STUB_DIR/forge_codex_review.sh" <<EOF
#!/bin/sh
echo "\$@" >> "$LOG"
exit \${DRIVER_RC:-0}
EOF
chmod +x "$STUB_DIR/forge_codex_review.sh"

# Run the real runner with the stub sitting beside it as its driver.
cp "$RUNNER" "$STUB_DIR/codex_review_queue.sh"
Q="$STUB_DIR/spool"
run() { CODEX_REVIEW_QUEUE="$Q" REVIEW_TIMEOUT=30 bash "$STUB_DIR/codex_review_queue.sh" --once 2>&1; }
req() { mkdir -p "$Q/pending"; printf '%s' "$1" > "$Q/pending/$2.json"; }
calls() { [ -f "$LOG" ] && wc -l < "$LOG" | tr -d ' ' || echo 0; }
reset() { rm -rf "$Q" "$LOG"; : > "$LOG" 2>/dev/null || { mkdir -p "$STUB_DIR"; : > "$LOG"; }; }

# ── 1. a well-formed request runs the driver with --pr ───────────────────────────
reset
req '{"kind":"codex_review","pr":3613,"dry_run":false}' "1000-3613"
run >/dev/null
[ "$(calls)" = "1" ] && grep -q '^--pr 3613$' "$LOG" \
  && ok "runs the driver for the requested PR" \
  || bad "driver not invoked correctly" "$(cat "$LOG" 2>/dev/null)"
[ -f "$Q/done/1000-3613.json" ] && ok "writes a result file" || bad "no result file"
grep -q '"status":"ok"' "$Q/done/1000-3613.json" 2>/dev/null \
  && ok "result reports ok on success" || bad "wrong result: $(cat "$Q/done/1000-3613.json" 2>/dev/null)"

# ── 2. the request is consumed, so a rerun cannot double-review ──────────────────
reset
req '{"kind":"codex_review","pr":7}' "1000-7"
run >/dev/null
run >/dev/null
[ "$(calls)" = "1" ] && ok "consumed request is not re-run" \
                    || bad "driver ran $(calls) times for one request"

# ── 3. dry_run is honoured (no posting) ───────────────────────────────────────────
reset
req '{"kind":"codex_review","pr":9,"dry_run":true}' "1000-9"
run >/dev/null
grep -q -- '--dry-run' "$LOG" && ok "dry_run request passes --dry-run to the driver" \
                              || bad "dry_run ignored" "$(cat "$LOG")"

# ── 4. HOSTILE / MALFORMED requests are refused, never executed ─────────────────
for bad_pr in '12; rm -rf /' '$(whoami)' '`id`' 'abc' '0' '-5' '' '3613 3614'; do
  reset
  req "{\"kind\":\"codex_review\",\"pr\":\"$bad_pr\"}" "1000-x"
  out="$(run)"
  if [ "$(calls)" = "0" ] && ls "$Q/done"/1000-x.json >/dev/null 2>&1; then
    ok "refuses pr=${bad_pr@Q} without invoking the driver"
  else
    bad "EXECUTED a request with pr=${bad_pr@Q}" "driver calls: $(calls)"
  fi
done

# ── 5. a request of the wrong kind is refused ────────────────────────────────────
reset
req '{"kind":"something_else","pr":42}' "1000-y"
run >/dev/null
[ "$(calls)" = "0" ] && ok "refuses a request that is not a codex_review" \
                    || bad "ran a non-codex_review request"

# ── 6. a failed driver run is reported as error, not ok ──────────────────────────
reset
req '{"kind":"codex_review","pr":55}' "1000-55"
DRIVER_RC=3 CODEX_REVIEW_QUEUE="$Q" REVIEW_TIMEOUT=30 \
  bash "$STUB_DIR/codex_review_queue.sh" --once >/dev/null 2>&1
grep -q '"rc":3' "$Q/done/1000-55.json" 2>/dev/null && grep -q '"status":"error"' "$Q/done/1000-55.json" \
  && ok "a failed review is recorded as error with its rc" \
  || bad "failure misrecorded: $(cat "$Q/done/1000-55.json" 2>/dev/null)"

# ── 7. an empty queue is a no-op, not an error ───────────────────────────────────
reset
mkdir -p "$Q/pending" "$Q/done"
out="$(run)"; rc=$?
[ "$rc" -eq 0 ] && [ "$(calls)" = "0" ] && ok "empty queue exits 0 and does nothing" \
                                   || bad "empty queue: rc=$rc calls=$(calls)"

# ── 8. --status reports counts without running anything ──────────────────────────
reset
req '{"kind":"codex_review","pr":1}' "1000-1"
out="$(CODEX_REVIEW_QUEUE="$Q" bash "$STUB_DIR/codex_review_queue.sh" --status 2>&1)"
grep -q 'pending: 1' <<< "$out" && [ "$(calls)" = "0" ] \
  && ok "--status reports pending count without draining" \
  || bad "--status wrong or drained the queue: $out"

printf '\n  %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
