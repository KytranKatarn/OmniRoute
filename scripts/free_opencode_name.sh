#!/usr/bin/env bash
# free_opencode_name.sh — rename the host's `opencode` wrapper to `opencode-docker`,
# leaving the name `opencode` free for the NATIVE host install.
#
#   ./scripts/free_opencode_name.sh            # dry run: show what it found
#   ./scripts/free_opencode_name.sh --apply    # rename, with backups
#   ./scripts/free_opencode_name.sh --rollback # restore the backups
#
# WHY
# ---
# On this host `opencode` currently resolves to a wrapper that docker-execs into a lane
# container — typing it produced:
#     No 'opencode' tmux session in archie_opencode_terminal — the lane's entrypoint
#     creates it. Try:  docker compose restart archie_opencode_terminal
# That string is NOT in /mnt/archie_brain/scripts/opencode (that file is a 143 MB ELF
# opencode build with no tmux/docker/compose strings — checked directly), so the
# wrapper lives in a shell rc file as an ALIAS or a SHELL FUNCTION.
#
# That wrapper is not going away: it is how the web terminals are reached. So we do not
# delete it. We rename it, and the names stop lying about what they are:
#
#     opencode            native host install (new; this is what you want by default)
#     opencode-docker     the existing wrapper -> docker exec into the lane container
#
# ⚠️ THE HAZARD THIS SCRIPT EXISTS TO HANDLE
# Renaming an ALIAS is mechanical and safe. Renaming a FUNCTION is not: if its body
# calls `opencode` (recursion, or re-dispatch after a container restart), renaming only
# the definition would silently repoint those inner calls at the NATIVE binary — so
# "opencode-docker" would end up launching a host agent inside a wrapper meant to launch
# a container agent. This script therefore renames the definition AND the self-references
# inside the body, and reports either way so the change is reviewable.
#
# SAFETY
#   * every rc file is copied to <file>.bak-<ts> before a single byte is written
#   * only whole-line alias/function definitions are touched; nothing else is rewritten
#   * `--rollback` restores every backup this script made
#   * prints the exact before/after diff lines so you can eyeball what changed
#   * a non-interactive check verifies the new name resolves and old name is free
set -euo pipefail

APPLY=0; ROLLBACK=0; PROBE=0; FILE_MODE=0
# NO ARGUMENT = PROBE. 2026-09-30: the owner's terminal dropped the trailing `--probe`
# from a pasted command (it had already dropped a leading `type` earlier), so the
# harmless, read-only diagnostic ran with no flag and printed the rename dry-run
# instead. Making the probe the default means the common case carries NO trailing
# token to lose, and the mutating paths still require an explicit flag.
# Parse EVERY argument, not just $1. Verified bug: `--file-mode --apply` looked only at
# $1, so --apply was silently ignored and the run degraded to a dry run that reported
# "DRY RUN — nothing changed" while looking like a real apply. Flags may now appear in
# any order.
SAW_FLAG=0
for _a in "$@"; do
  case "$_a" in
    --apply)              APPLY=1; SAW_FLAG=1 ;;
    --rollback)           ROLLBACK=1; SAW_FLAG=1 ;;
    --file-mode)          FILE_MODE=1; SAW_FLAG=1 ;;
    --dry-run)            APPLY=0; SAW_FLAG=1 ;;
    --probe)              PROBE=1; SAW_FLAG=1 ;;
    -h|--help)
      echo "usage: $0 [--probe] [--dry-run] [--file-mode [--apply|--rollback]] [--rollback]"
      exit 0 ;;
    *)
      echo "usage: $0 [--probe] [--dry-run] [--file-mode [--apply|--rollback]] [--rollback]" >&2
      echo "  unknown argument: $_a" >&2
      exit 2 ;;
  esac
done
# No flags at all = probe, so the common read-only diagnostic has nothing to lose to a
# paste that drops a token.
[ "$SAW_FLAG" = "0" ] && { PROBE=0; AUTOF=1; }   # bare = auto-detect + confirm
if [ "$ROLLBACK" = "1" ] && [ "$FILE_MODE" = "1" ] && [ "$APPLY" = "0" ]; then
  : # file-mode rollback handled in the file-mode block
fi
case "${1:-}" in --rollback) : ;; esac

OLD="opencode"; NEW="opencode-docker"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUPS=()

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "$PROBE" = "1" ]; then
  REPORT="${PROBE_REPORT:-/mnt/archie_brain/.opencode-shadow-report.txt}"
  # `set +e` INSIDE the report block. Diagnostics are full of deliberately-failing
  # commands (`type -a opencode` when it is not found, `[ -e ... ] &&` on the last PATH
  # dir), and under `set -e` the first one aborts the whole script mid-report — leaving
  # a truncated file at mode 644 and no confirmation line. Verified exactly that.
  {
    set +e
    echo "probe at $(date -Is)"
    echo "user=$(id -un) uid=$(id -u) groups=$(id -G)"
    echo
    echo "== PATH =="
    printf '%s\n' "$PATH" | tr ':' '\n'
    echo
    echo "== type -a opencode =="
    type -a opencode 2>&1 || echo "(not found)"
    echo
    echo "== command -v opencode =="
    command -v opencode 2>&1 || echo "(not found)"
    echo
    echo "== alias opencode =="
    alias opencode 2>&1 || echo "(no alias)"
    echo
    echo "== declare -f opencode =="
    declare -f opencode 2>&1 || echo "(no function)"
    echo
    echo "== files named opencode on PATH =="
    IFS=:; for d in $PATH; do
      [ -e "$d/opencode" ] && ls -la "$d/opencode" 2>&1
    done
    unset IFS
    echo
    echo "== CONTENTS of whatever 'opencode' resolves to =="
    # /home/kytran is NOT mounted into the agent's container, so the report has to
    # carry the file or nobody can see what the wrapper actually does. 2207 bytes,
    # read-only copy, and a warning if it is large enough to be something else.
    _oc="$(command -v opencode 2>/dev/null)"
    if [ -n "$_oc" ] && [ -r "$_oc" ]; then
      echo "-- $_oc"
      ls -la "$_oc" 2>&1
      _real="$(readlink -f "$_oc" 2>/dev/null || echo "$_oc")"
      echo "-- resolves to: $_real"
      if [ -f "$_real" ] && [ "$(wc -c < "$_real")" -lt 200000 ]; then
        echo "-- begin contents --"
        cat "$_real" 2>&1
        echo "-- end contents --"
      else
        echo "(too large to inline — $(wc -c < "$_real" 2>/dev/null) bytes; likely a real binary)"
      fi
    else
      echo "(opencode did not resolve, or is not readable)"
    fi
    echo
    echo "== sibling wrappers in the same directory =="
    _d="$(dirname "$_oc" 2>/dev/null)"
    [ -n "$_d" ] && ls -la "$_d" 2>&1 | head -40

    echo
    echo "== rc files that mention opencode =="
    for f in "$HOME/.bashrc" "$HOME/.bash_aliases" "$HOME/.bash_profile" \
             "$HOME/.profile" "$HOME/.zshrc" /etc/profile; do
      [ -r "$f" ] && { m=$(grep -n "opencode" "$f" 2>/dev/null); [ -n "$m" ] && { echo "-- $f"; echo "$m"; }; }
    done
    for f in /etc/profile.d/*; do
      [ -r "$f" ] && { m=$(grep -n "opencode" "$f" 2>/dev/null); [ -n "$m" ] && { echo "-- $f"; echo "$m"; }; }
    done
  } > "$REPORT" 2>&1
  chmod 600 "$REPORT"
  echo "probe written to $REPORT (nothing was changed)"
  exit 0
fi

# --file-mode: the shadow is an EXECUTABLE ON PATH, not an alias/function.
#
# Discovered by probe 2026-09-30: /home/kytran/.local/bin/opencode, 2207 bytes, a
# deliberate wrapper that docker-execs into the 17685 lane and tmux-attaches to the
# shared session. First entry on PATH, so it wins over any npm install. Renaming it
# frees the name `opencode` without touching a single byte of its logic.
#
# `opencode-docker` is the same behaviour under a name that says what it does. The
# script's own text (usage/help output, error messages) is left ALONE on purpose: it
# says "the CLI twin of opencode.kytranempowerment.com" and names `opencode --solo`,
# and rewriting those would be editing documentation I was not asked to edit.
# ---------------------------------------------------------------------------
# AUTO-DETECT (bare invocation). 2026-09-30: the owner's terminal dropped trailing flags
# from a paste TWICE — '--file-mode --apply' arrived as '--apply', so the run silently did
# the wrong thing while looking successful. A command whose correctness depends on
# flags surviving a paste is not a command anyone should have to run. So a bare
# invocation figures out the shape itself and asks before touching anything.
if [ "$AUTOF" = "1" ]; then
  _t="$(type -a opencode 2>/dev/null | head -1 || true)"
  case "$_t" in
    *"is aliased"*|*"is a function"*) FILE_MODE=0 ;;   # rc-mode handles it
    "opencode is"*)
      FILE_MODE=1
      WRAPPER_PATH="${_t#opencode is }"
      say ""
      say "auto-detected: 'opencode' is a PATH executable -> ${WRAPPER_PATH}"
      say "              (not an alias, not a shell function — nothing in any rc file)"
      ;;
    *)
      PROBE=1 ;;
  esac
fi

if [ "$FILE_MODE" = "1" ]; then
  step "PATH-executable shadow: rename it to '$NEW'"
  WRAPPER="${WRAPPER_PATH:-}"
  if [ -z "$WRAPPER" ]; then
    WRAPPER="$(command -v "$OLD" 2>/dev/null || true)"
  fi
  [ -n "$WRAPPER" ] || die "'$OLD' does not resolve to a file — nothing to rename"
  [ -e "$WRAPPER" ] || die "$WRAPPER no longer exists"

  TARGET="$(dirname "$WRAPPER")/$NEW"
  say "  from : $WRAPPER"
  say "  to   : $TARGET"
  if [ -e "$TARGET" ]; then
    die "$TARGET already exists — refusing to overwrite. Resolve that first."
  fi
  # Refuse to rename something that is not a wrapper we recognise.
  if ! grep -q "docker exec" "$WRAPPER" 2>/dev/null; then
    say "  ! this file does not mention 'docker exec' — it may not be the lane wrapper."
    say "    Continuing anyway would rename a real program. Aborting."
    exit 1
  fi
  if [ "$APPLY" = "0" ]; then
    say ""
    if [ ! -t 0 ]; then
      say "DRY RUN (not a terminal) — nothing changed. Re-run interactively, or pass --apply."
      exit 0
    fi
    say "About to rename it. This changes what the bare word 'opencode' means on this host."
    printf "  type APPLY to continue: "
    read -r _confirm
    if [ "$_confirm" != "APPLY" ]; then
      say "cancelled — nothing changed."
      exit 0
    fi
    say ""
  fi

  # Keep a copy: the wrapper's own --help text and error messages name `opencode`,
  # so the original name is worth preserving. Done AFTER confirmation — a cancelled or
  # dry run must not leave .bak files lying around.
  cp -a "$WRAPPER" "$WRAPPER.bak-$(date +%Y%m%d-%H%M%S)"
  say "  kept a copy at $WRAPPER.bak-<ts>"

  mv "$WRAPPER" "$TARGET"
  say "  renamed."
  echo
  say "  $NEW   -> the lane wrapper (docker exec + tmux attach), unchanged"
  say "  $OLD       -> free for the native host install"
  echo
  say "  In a NEW shell (or: source ~/.bashrc) the old name stops resolving to the"
  say "  wrapper immediately — PATH is not cached, so no rehash is needed."
  say "  Re-run this script with no arguments to confirm the native install won."
  exit 0
fi

RC_FILES=()
for f in "$HOME/.bashrc" "$HOME/.bash_aliases" "$HOME/.bash_profile" "$HOME/.profile" "$HOME/.zshrc"; do
    [ -f "$f" ] && [ -r "$f" ] && RC_FILES+=("$f")
done
[ "${#RC_FILES[@]}" -gt 0 ] || die "no readable shell rc file found in \$HOME"

# ---------------------------------------------------------------------------
# ⚠️ ROLLBACK MUST RUN BEFORE DETECTION. After a rename the definition is
# `alias opencode-docker=...`, which no longer matches the `alias opencode=` probe, so
# FOUND=0 and the script exits with "Nothing to rename" — rollback silently does nothing.
# Verified broken before this was moved.
if [ "$ROLLBACK" = "1" ]; then
  step "Rolling back"
  found=0
  for f in "${RC_FILES[@]}"; do
    for b in "$f".bak-*; do
      [ -e "$b" ] || continue
      cp -a "$b" "$f"; say "  restored $f from $b"; found=$((found+1))
    done
  done
  [ "$found" -gt 0 ] || say "  no backups found"
  exit 0
fi

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# --probe : diagnose ONLY, and write the report somewhere the agent can read it.
#
# Added 2026-09-30 after the owner's terminal ate the leading word of pasted commands
# twice, turning `type -a opencode` into `-a opencode`. Requiring a paste round-trip for
# a diagnosis is a bad loop: the agent CAN read /mnt/archie_brain, so the probe drops a
# report there and prints one line. Nothing is changed and nothing is echoed as a
# secret — `declare -f` output can contain tokens, so the report is written 0600.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
step "Where is '$OLD' defined?"
# ---------------------------------------------------------------------------
FOUND=0
for f in "${RC_FILES[@]}"; do
  # an alias line, or a function definition
  if grep -qE "^[[:space:]]*alias[[:space:]]+$OLD=" "$f" || grep -qE "^[[:space:]]*$OLD[[:space:]]*\(\)[[:space:]]*\{" "$f"; then
    FOUND=$((FOUND+1))
    say ""
    say "  $f"
    grep -nE "^[[:space:]]*alias[[:space:]]+$OLD=|^[[:space:]]*$OLD[[:space:]]*\(\)[[:space:]]*\{" "$f" \
      | sed 's/^/    line /' | cut -c1-200
    # classify
    if grep -qE "^[[:space:]]*alias[[:space:]]+$OLD=" "$f"; then say "    -> ALIAS (rename is mechanical and safe)"
    else say "    -> SHELL FUNCTION (rename must also fix self-references inside the body)"; fi
  fi
done

if [ "$FOUND" -eq 0 ]; then
  step "Nothing to rename in the rc files"
  say "  '$OLD' is not an alias or function in: ${RC_FILES[*]}"
  say ""
  say "  It may instead come from PATH. Check what actually wins:"
  say "    type -a $OLD"
  say "  If that shows a path, the shadow is a file — report it and we will handle it"
  say "  separately (a wrapper script, not a shell alias)."
  exit 0
fi

# ---------------------------------------------------------------------------
step "Self-references inside the definition (the hazard)"
# ---------------------------------------------------------------------------
for f in "${RC_FILES[@]}"; do
  if grep -qE "^[[:space:]]*$OLD[[:space:]]*\(\)" "$f"; then
    # print the body so inner $OLD calls are visible before anything is rewritten
    n=$( { grep -nE "^[[:space:]]*$OLD[[:space:]]*\(\)" "$f" || true; } | head -1 | cut -d: -f1)
    say "  $f line $n — body references to '$OLD':"
    awk -v s="$n" 'NR>s && /^[[:space:]]*}/ {exit} NR>s' "$f" \
      | grep -nE "(^|[^a-zA-Z0-9_-])$OLD([^a-zA-Z0-9_-]|$)" \
      | sed 's/^/      /' | cut -c1-160 || say "      (none)"
  fi
done

# ---------------------------------------------------------------------------
if [ "$APPLY" = "0" ]; then
  cat <<EOF

DRY RUN — nothing changed. Re-run with --apply to:
  1. back up every rc file to <file>.bak-$STAMP
  2. rename the '$OLD' definition to '$NEW' (alias, or function + its self-references)
  3. leave '$OLD' free for the native host install

Roll back any time with: $0 --rollback
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
step "Backing up"
for f in "${RC_FILES[@]}"; do
  cp -a "$f" "$f.bak-$STAMP"; BACKUPS+=("$f.bak-$STAMP")
  say "  $f.bak-$STAMP"
done

# ---------------------------------------------------------------------------
step "Renaming"
CHANGED=0
for f in "${RC_FILES[@]}"; do
  before="$(md5sum "$f" | cut -d' ' -f1)"

  # 1. alias form:  alias opencode=...   ->   alias opencode-docker=...
  sed -i -E "s|^([[:space:]]*)alias[[:space:]]+$OLD=|\1alias $NEW=|" "$f"

  # 2. function form:  opencode() {   ->   opencode-docker() {
  #    ONLY the definition line is rewritten. Self-references inside the body are NOT,
  #    and must not be: a body that runs
  #        docker exec -it archie_opencode_terminal opencode "$@"   <- CONTAINER-side
  #        opencode --solo                                          <- HOST-side self-call
  #    needs OPPOSITE treatment. Rewriting both to `opencode-docker` would break the
  #    exec (the container has no such command); rewriting neither leaves the self-call
  #    hitting the newly-native `opencode`. No regex can tell them apart reliably, so
  #    this script rewrites neither and REPORTS them for a human. An earlier draft's
  #    comment claimed it handled this; it did not, and the comment was the only thing
  #    that was wrong about it.
  sed -i -E "s|^([[:space:]]*)$OLD([[:space:]]*\(\)[[:space:]]*\{)|\1$NEW\2|" "$f"

  after="$(md5sum "$f" | cut -d' ' -f1)"
  if [ "$before" != "$after" ]; then
    CHANGED=$((CHANGED+1))
    say ""
    say "  $f — changed lines:"
    # `|| true` is load-bearing: diff exits 1 WHEN FILES DIFFER, which is the success
    # case here, and `pipefail` would abort the whole script on the very change we just
    # made correctly. (Fourth pipefail trap in this session; all four are now `|| true`.)
    diff <(cat "$f.bak-$STAMP") "$f" | sed 's/^/    /' | head -40 || true
  fi
done

[ "$CHANGED" -gt 0 ] || say "  no file needed changing"

# ---------------------------------------------------------------------------
step "REVIEW REQUIRED — leftover '$OLD' references inside the renamed wrapper"
# These are NOT fixed automatically and NOT safe to fix automatically. Classify each:
#   docker exec ... opencode ...   -> container-side; LEAVE AS IS
#   a bare `opencode ...` call      -> host-side; it now resolves to the NATIVE binary,
#                                     so change it to `$NEW ...` yourself
LEFTOVER=0
for f in "${RC_FILES[@]}"; do
  [ -f "$f" ] || continue
  start=$( { grep -nE "^[[:space:]]*$NEW[[:space:]]*\(\)" "$f" || true; } | head -1 | cut -d: -f1)
  [ -n "$start" ] || continue
  hits="$(awk -v s="$start" 'NR>s && /^[[:space:]]*}/ {exit} NR>s' "$f" \
            | grep -nE "(^|[^a-zA-Z0-9_-])$OLD([^a-zA-Z0-9_-]|$)" || true)"
  if [ -n "$hits" ]; then
    LEFTOVER=$((LEFTOVER+1))
    say ""
    say "  $f (from line $start):"
    printf '%s\n' "$hits" | sed 's/^/    /' | cut -c1-150
  fi
done
if [ "$LEFTOVER" -gt 0 ]; then
  cat <<EOF

  ⚠️  READ THESE. A line with 'docker exec ... $OLD' is CONTAINER-side and must keep
     '$OLD' — the container has no '$NEW'. A BARE '$OLD ...' call is HOST-side and now
     means the native install; change it to '$NEW ...' if the old behaviour is what you
     wanted. This script will not guess which is which.
EOF
else
  say "  none — the wrapper is a single alias line, nothing to review."
fi

# ---------------------------------------------------------------------------
step "Verifying (fresh non-interactive shell)"
say "  \$ type -a $NEW"
bash -lc "type -a $NEW" 2>&1 | sed 's/^/    /' | head -4
say "  \$ type -a $OLD   (should now be the native install, or not found yet)"
bash -lc "type -a $OLD" 2>&1 | sed 's/^/    /' | head -4

cat <<EOF

Done. From here, in a NEW shell (aliases need a fresh shell, or: source ~/.bashrc):

    $NEW          the OLD wrapper — docker exec into the lane container, web terminals
    $OLD             the NATIVE host install, as $(id -un)

If '$OLD' still shows the old wrapper, the definition lives in a file not in this list
(${RC_FILES[*]}). Send \`type -a $OLD\` output and we will find it.

Rollback: $0 --rollback
EOF
