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
RUNNING="$QUEUE/running"
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
  # CODEX REVIEW FIX: claimed-but-unfinished requests live in running/; without this the
  # count was invisible and a stuck review looked like an empty queue.
  printf 'running: %s\n' "$(ls -1 "$RUNNING" 2>/dev/null | grep -c '\.json$')"
  printf 'done:    %s\n' "$(ls -1 "$DONE" 2>/dev/null | grep -c '\.json$')"
  exit 0
fi

[ -f "$DRIVER" ] || { echo "FATAL: driver not found at $DRIVER" >&2; exit 1; }

mkdir -p "$PENDING" "$RUNNING" "$DONE" 2>/dev/null || {
  echo "FATAL: cannot create $QUEUE (need write access)" >&2; exit 1; }

# Read one field out of a flat JSON request as its RAW value (surrounding quotes
# stripped, surrounding whitespace trimmed). Deliberately not a general JSON parser: the
# platform writes these, and the only values that reach a shell command downstream are
# the PR number and the repo, which _valid_pr / _valid_repo then judge.
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

# CODEX REVIEW FIX: the queued `repo` was written by the service and then ignored — the
# driver was always invoked with the PR number alone, so a PR from another repository was
# reviewed against the driver's DEFAULT repo: the wrong code entirely, or a "no such PR"
# if the number does not exist there. Validate it here and pass it through.
_valid_repo() {
  # owner/name, no shell metacharacters, no leading dash (would read as a flag).
  case "$1" in
    ''|-*) return 1 ;;
    *[!A-Za-z0-9._/-]*) return 1 ;;
    */*/*) return 1 ;;
    */*) return 0 ;;
    *) return 1 ;;
  esac
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

# CODEX REVIEW FIX (atomic claim): the request used to stay in pending/ for the whole
    # review, so two overlapping runners both picked it up and both posted a comment, and
    # a runner killed after posting but before the cleanup `mv` repeated the whole review
    # on its next tick. Claim it FIRST by renaming into running/ — rename is atomic on the
    # same filesystem, so exactly one runner can win. A crash mid-review now leaves the
    # file in running/ rather than re-running it, which is the safe direction to fail.
    local claim="$RUNNING/$id.json"
    if ! mv "$req" "$claim" 2>/dev/null; then
      echo "  [$id] claimed by another runner — skipping" >&2
      return 0
    fi

    pr="$(_field "$claim" pr)"
    if ! _valid_pr "$pr"; then
      printf '{"id":"%s","status":"refused","error":"missing or non-numeric pr"}\n' "$id" \
        > "$DONE/$id.json"
      mv "$claim" "$DONE/$id.json.bad" 2>/dev/null
      echo "  refused $id (bad pr)" >&2
      return 0
    fi

    repo="$(_field "$claim" repo)"
    # The service serialises an absent repo as JSON null (`repo or None`), so `null`
    # must mean "not supplied" rather than being treated as a malformed repo name.
    [ "$repo" = "null" ] && repo=""
    # CODEX REVIEW FIX: `repo` was written by the platform and then ignored entirely, so a
    # PR from another repository was reviewed against the driver's DEFAULT repo — the wrong
    # code, or "no such PR" if the number does not exist there. It is OPTIONAL: absent or
    # null means "the driver's default repo", which is the common single-repo case and
    # must keep working. When present it must be a safe owner/name or the request is
    # refused rather than passed to the driver.
    use_repo=0
    if [ -n "$repo" ]; then
      if ! _valid_repo "$repo"; then
        printf '{"id":"%s","status":"refused","error":"unsafe repo"}\n' "$id" \
          > "$DONE/$id.json"
        mv "$claim" "$DONE/$id.json.bad" 2>/dev/null
        echo "  refused $id (bad repo)" >&2
        return 0
      fi
      use_repo=1
    fi

    if [ "$use_repo" -eq 1 ]; then
      echo "  [$id] reviewing $repo PR #$pr ..."
    else
      echo "  [$id] reviewing PR #$pr (driver default repo) ..."
    fi
    local log="$DONE/$id.log"
    # --post is the driver's own default. `dry_run` in the request is honoured so an
    # operator can rehearse from the UI without writing to GitHub.
    local args=(--pr "$pr")
    grep -q '"dry_run"[[:space:]]*:[[:space:]]*true' "$claim" && args+=(--dry-run)
    # Pass the repo through when we have one, or a cross-repo PR reviews the wrong code.
    # `timeout` EXECs its argument, so `timeout ... bash "$DRIVER"` is NOT enough when
    # $DRIVER is 0644 — it resolves the path, tries to exec it, and dies rc=126 with
    # "Permission denied". Measured live: codex_pr_review.sh merged as 100644 and every
    # queued review failed that way, reported as rc=1.
    #
    # `bash -c 'exec bash "$0" "$@"'` hands the path to bash as an ARGUMENT, so the
    # script is read by the interpreter and its exec bit is irrelevant. That makes the
    # whole class of file-mode failure impossible from the runner, whatever git recorded.
    _drive() { exec bash "$DRIVER" "$@"; }
    if [ "$use_repo" -eq 1 ]; then
      REPO="$repo" timeout "${REVIEW_TIMEOUT:-900}" bash -c 'exec bash "$0" "$@"' \
        "$DRIVER" "${args[@]}" > "$log" 2>&1
    else
      timeout "${REVIEW_TIMEOUT:-900}" bash -c 'exec bash "$0" "$@"' \
        "$DRIVER" "${args[@]}" > "$log" 2>&1
    fi
    rc=$?

    mv "$claim" "$DONE/$id.json.req" 2>/dev/null
    {
      printf '{"id":"%s","pr":%s,"repo":"%s","rc":%s,"status":"' "$id" "$pr" "$repo" "$rc"
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
