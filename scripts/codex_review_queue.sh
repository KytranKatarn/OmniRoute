#!/usr/bin/env bash
# codex_review_queue.sh — host-side runner for CODEX reviews requested from Repair Bay.
#
# WHY THIS IS A QUEUE AND NOT AN SSH CALL
#   The Repair Bay button used to shell out over ssh. It cannot: the platform container's
#   key is not authorized on its own host (verified — every address returns
#   "Permission denied (publickey)"), and /mnt/archie_brain is mounted READ-ONLY in the
#   container, so it cannot write a request into the repo either.
#
#   What IS shared and writable from both sides is /mnt/archie_sandbox. So the platform
#   drops a small JSON request in a spool directory and this script picks it up. The web
#   app gains no code execution and no new credential — it writes a file, exactly like a
#   print spool. codex itself only ever runs here, on the host, where the binary and the
#   git credentials live.
#
# FLOW
#   platform  -> $QUEUE/pending/<id>.json      (request)
#   this      -> runs forge_codex_review.sh --pr N
#   this      -> $QUEUE/done/<id>.json         (result, incl. the reviewer's exit code)
#
# USAGE
#   scripts/codex_review_queue.sh --once      # drain the queue and exit (cron-friendly)
#   scripts/codex_review_queue.sh --loop      # keep draining (foreground service)
#   scripts/codex_review_queue.sh --status    # show pending/done counts
#
# Environment:
#   CODEX_REVIEW_QUEUE   spool dir   (default /mnt/archie_sandbox/.codex-review-queue)
#   REVIEW_TIMEOUT       seconds     (default 900, same default as the driver)
#   POLL_SECONDS         loop sleep  (default 60)
set -uo pipefail

QUEUE="${CODEX_REVIEW_QUEUE:-/mnt/archie_sandbox/.codex-review-queue}"
PENDING="$QUEUE/pending"
DONE="$QUEUE/done"
POLL_SECONDS="${POLL_SECONDS:-60}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DRIVER="$SCRIPT_DIR/forge_codex_review.sh"

MODE="once"
case "${1:---once}" in
  --once)   MODE="once" ;;
  --loop)   MODE="loop" ;;
  --status) MODE="status" ;;
  -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
  *) echo "unknown flag: $1" >&2; exit 2 ;;
esac

if [ "$MODE" = "status" ]; then
  printf 'queue:   %s\n' "$QUEUE"
  printf 'pending: %s\n' "$(ls -1 "$PENDING" 2>/dev/null | grep -c '\.json$')"
  printf 'done:    %s\n' "$(ls -1 "$DONE" 2>/dev/null | grep -c '\.json$')"
  exit 0
fi

[ -f "$DRIVER" ] || { echo "FATAL: driver not found at $DRIVER" >&2; exit 1; }

mkdir -p "$PENDING" "$DONE" 2>/dev/null || {
  echo "FATAL: cannot create $QUEUE (need write access)" >&2; exit 1; }

# Read one field out of a flat JSON request as its RAW value (surrounding quotes
# stripped, surrounding whitespace trimmed). Deliberately not a general JSON parser: the
# platform writes these, and the only value that reaches a shell command downstream is
# the PR number, which _valid_pr then requires to be pure digits.
#
# Capturing the WHOLE value matters. An earlier version matched only the leading digits
# after the colon, so `"pr":"12; rm -rf /"` yielded `12` and the request was ACCEPTED —
# no injection, since the value stayed numeric, but a malformed request was silently
# coerced instead of refused. Test 4 caught it. Extract the entire value and let
# _valid_pr judge it.
_field() {
  sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\("[^"]*"\|[^,}]*\).*/\1/p' "$1" \
    | head -1 \
    | sed 's/^"//; s/"$//; s/^[[:space:]]*//; s/[[:space:]]*$//'
}

_valid_pr() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *)           [ "$1" -gt 0 ] 2>/dev/null || return 1; return 0 ;;
  esac
}

drain_one() {
  local req="$1" id pr rc
  id="$(basename "$req" .json)"

  # A malformed or hostile request must be REJECTED and quarantined, not executed.
  if ! grep -q '"kind"[[:space:]]*:[[:space:]]*"codex_review"' "$req" 2>/dev/null; then
    mv "$req" "$DONE/$id.json" 2>/dev/null
    printf '{"id":"%s","status":"refused","error":"request is not a codex_review"}\n' "$id" \
      > "$DONE/$id.json"
    echo "  refused $id (wrong kind)" >&2
    return 0
  fi

  pr="$(_field "$req" pr)"
  if ! _valid_pr "$pr"; then
    printf '{"id":"%s","status":"refused","error":"missing or non-numeric pr"}\n' "$id" \
      > "$DONE/$id.json"
    mv "$req" "$DONE/$id.json.bad" 2>/dev/null
    echo "  refused $id (bad pr)" >&2
    return 0
  fi

  echo "  [$id] reviewing PR #$pr ..."
  local log="$DONE/$id.log"
  # --post is the driver's own default. `dry_run` in the request is honoured so an
  # operator can rehearse from the UI without writing to GitHub.
  local args=(--pr "$pr")
  grep -q '"dry_run"[[:space:]]*:[[:space:]]*true' "$req" && args+=(--dry-run)

  # Invoked via `bash` deliberately, not executed directly. The driver merged as mode
  # 100644 (its exec bit was never recorded), so calling it directly fails rc=126 —
  # "permission denied" — and every queued review would report an error that looks like
  # a codex failure rather than a file-mode one. `bash` on the path removes that whole
  # class of problem. The exec bit is fixed too; this is the belt to that braces.
  timeout "${REVIEW_TIMEOUT:-900}" bash "$DRIVER" "${args[@]}" > "$log" 2>&1
  rc=$?

  # Move the request out of pending FIRST so a crash cannot double-run it on the next
  # tick, then write the result the platform polls for.
  mv "$req" "$DONE/$id.json.req" 2>/dev/null
  {
    printf '{"id":"%s","pr":%s,"rc":%s,"status":"' "$id" "$pr" "$rc"
    if [ "$rc" -eq 0 ]; then printf 'ok'; else printf 'error'; fi
    printf '","finished":"%s","log":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$log"
  } > "$DONE/$id.json"

  echo "  [$id] PR #$pr finished rc=$rc"
}

drain() {
  local n=0 f
  for f in "$PENDING"/*.json; do
    [ -e "$f" ] || continue
    drain_one "$f"
    n=$((n + 1))
  done
  [ "$n" -gt 0 ] && echo "==> processed $n request(s)"
  return 0
}

case "$MODE" in
  once) drain ;;
  loop)
    echo "==> codex review queue watching $QUEUE (poll ${POLL_SECONDS}s, Ctrl-C to stop)"
    while true; do
      drain
      sleep "$POLL_SECONDS"
    done
    ;;
esac
