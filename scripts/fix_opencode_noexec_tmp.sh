#!/usr/bin/env bash
# fix_opencode_noexec_tmp.sh — opencode will not start: its TUI cannot load.
#
#   ./scripts/fix_opencode_noexec_tmp.sh      # diagnose, then confirm
#   ./scripts/fix_opencode_noexec_tmp.sh --rollback
#
# THE ERROR
# ---------
#   Failed to initialize OpenTUI render library:
#   Failed to open library "/tmp/.9adb69bde2f3fd97-00000001.so":
#   failed to map segment from shared object
#
# WHAT IS HAPPENING
# -----------------
# OpenTUI is a native module. Bun extracts it as a shared object into the temp dir and
# dlopen()s it. dlopen of an EXECUTABLE mapping is refused on a `noexec` mount — and this
# host's /tmp is noexec. That is also why `bash /tmp/parity.sh` failed with "Permission
# denied" on 2026-09-30 even after chmod +x: the exec BIT was set; the MOUNT refused.
# Same root cause, different symptom, hours apart.
#
# The fix is to give opencode a temp dir on a normal filesystem. Both TMPDIR and
# BUN_TMPDIR are honoured by the binary (verified by string search), so TMPDIR is enough
# and is the more standard of the two.
#
# ⚠️ WHY THE INSTALLER SAID "✓ opencode 1.18.30"
# It checked `opencode --version`, which never initialises the TUI. So a green install
# check did not mean opencode could start. This script verifies by actually STARTING
# the TUI through a pty and reading its output — if OpenTUI still fails, it says so
# instead of reporting success.
#
# SCOPE
# The export is added to ~/.bashrc, so it applies to interactive shells. It does NOT
# touch system-wide TMPDIR, and it is deliberately NOT set inside this script's own
# environment beyond the verification step.
set -euo pipefail

TMPNEW="$HOME/.cache/opencode/tmp"
RC="$HOME/.bashrc"
MARKER="# --- opencode: temp dir must be exec-capable (see scripts/fix_opencode_noexec_tmp.sh) ---"
APPLY=0; ROLLBACK=0; SAW=0
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1; SAW=1 ;;
    --rollback) ROLLBACK=1; SAW=1 ;;
    -h|--help) echo "usage: $0 [--apply|--rollback]"; exit 0 ;;
    *) echo "usage: $0 [--apply|--rollback]" >&2; exit 2 ;;
  esac
done
say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

if [ "$ROLLBACK" = "1" ]; then
  step "Removing the block from $RC"
  [ -f "$RC" ] || die "$RC not found"
  python3 - "$RC" "$MARKER" <<'PY'
import sys
rc, marker = sys.argv[1], sys.argv[2]
lines = open(rc).read().splitlines(keepends=True)
out, skip = [], False
for ln in lines:
    st = ln.strip()
    if not skip and marker in ln:
        skip = True; continue
    if skip:
        # swallow the whole block we wrote: blank lines, '#' comments and the export.
        # An earlier version only handled blanks and the export, and left the comment
        # line behind — a half-removed block.
        if st == "" or st.startswith("#") or st.startswith("export TMPDIR="):
            continue
    skip = False
    out.append(ln)
open(rc, "w").writelines(out)
print("  removed %d line(s)" % (len(lines) - len(out)))
PY
  rmdir "$TMPNEW" 2>/dev/null || true
  say "  done — opencode will fail again until /tmp becomes exec-capable"
  exit 0
fi

# ---------------------------------------------------------------------------
step "Diagnosing"
# ---------------------------------------------------------------------------
command -v opencode >/dev/null || die "opencode is not on PATH — run the host installer first"
OC="$(command -v opencode)"
say "  opencode : $OC"

# Is /tmp actually noexec? Check the mount, not the file bit.
if grep -qE ' /tmp .*noexec' /proc/mounts 2>/dev/null; then
  say "  /tmp     : MOUNTED noexec  <- this is the cause"
  TMPISNOEXEC=1
else
  say "  /tmp     : not marked noexec on /proc/mounts"
  TMPISNOEXEC=0
fi
# Same check for the directory we intend to use.
mkdir -p "$TMPNEW" 2>/dev/null || die "cannot create $TMPNEW"
if grep -qE " ${TMPNEW%%/*} .*noexec" /proc/mounts 2>/dev/null || \
   grep -qE " / .*noexec" /proc/mounts 2>/dev/null && ! grep -qE ' / .*rw' /proc/mounts 2>/dev/null; then
  say "  $TMPNEW : looks noexec"
else
  say "  $TMPNEW : on a normal filesystem (exec-capable)"
fi
say "  disk     : $(df -h "$TMPNEW" 2>/dev/null | awk 'NR==2{print $4" free on "$6}')"

# ---------------------------------------------------------------------------
step "Testing the fix BEFORE touching your shell"
# ---------------------------------------------------------------------------
if TMPDIR="$TMPNEW" timeout 25 opencode --version >/dev/null 2>&1; then
  say "  --version works (it always did — it does not start the TUI)"
else
  say "  --version FAILED even with TMPDIR set — the problem may not be noexec at all."
fi

# The real test: start the TUI on a pty and see whether OpenTUI initialises.
DIAG="${TMPDIR_DIAG:-/mnt/archie_brain/.opencode-tui-diag.txt}"
say "  starting the TUI for 20s (TMPDIR and BUN_TMPDIR both set)…"
say "  full output -> $DIAG"
TUI_OUT="$(python3 - "$TMPNEW" "${DIAG:-}" <<'PY'
import os, pty, select, sys, time
tmp = sys.argv[1]
argv = ["opencode"]
diag = sys.argv[2] if len(sys.argv) > 2 else ""
env = dict(os.environ, TMPDIR=tmp, BUN_TMPDIR=tmp, TERM="xterm-256color")
pid, fd = pty.fork()
if pid == 0:
    os.execvpe(argv[0], argv, env)
buf = b""
deadline = time.time() + 20
try:
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 1.0)
        if r:
            try:
                d = os.read(fd, 65536)
            except OSError:
                break
            if not d: break
            buf += d
        pid_done, _ = os.waitpid(pid, os.WNOHANG)
        if pid_done:
            # exited; whatever it printed is the answer
            break
finally:
    try:
        os.write(fd, b"\x03")   # ctrl-c, then kill
    except OSError:
        pass
    time.sleep(0.3)
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    try: os.close(fd)
    except OSError: pass
if diag:
    # written AFTER collection — an earlier version referenced buf before it existed
    try:
        open(diag, "w").write(buf.decode(errors="replace"))
    except Exception as e:
        open(diag, "w").write("could not write diag: %s" % e)
sys.stdout.write(buf.decode(errors="replace"))
PY
)"
# Match the ERROR SIGNATURE, not the word "OpenTUI". A raw pty does not answer opencode's
# terminal capability queries ($p sequences), so the capture is messy, and grepping for a
# component name produced a FALSE POSITIVE on a TUI that had in fact started cleanly.
# Two runs disagreed: the shell variable said "OpenTUI", the on-disk capture said zero
# matches and showed the rendered banner. So: only the literal error strings count.
if printf '%s' "$TUI_OUT" | grep -qiE "failed to map segment|Unexpected error|Failed to initialize OpenTUI"; then
  say "  ✗ opencode still fails to start with TMPDIR=$TMPNEW"
  # Show ONLY the error lines. Printing the pty stream sprayed thousands of semicolon-
  # separated colour/graphics codes into the owner's shell, where bash tried to execute
  # them ("syntax error near unexpected token `;'"). Stripping escapes is not enough —
  # some of that output is genuinely ambiguous graphics protocol — so the raw capture
  # never goes to the terminal at all.
  printf '%s\n' "$TUI_OUT" | python3 -c '
import re,sys
c=sys.stdin.read()
c=re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\\\)","",c)
c=re.sub(r"\x1b\[[0-9;<>?]*[a-zA-Z]","",c)
c=re.sub(r"\x1b[0-9=>]","",c)
c=re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]","",c)
for l in c.splitlines():
    l=l.strip()
    if re.search(r"failed to map segment|Unexpected error|OpenTUI|Failed to initialize", l, re.I):
        print("      " + l[:160])
' || true
  say "    full capture: $DIAG"
  say "    NOT changing your shell. Paste that output."
  exit 1
fi
if printf '%s' "$TUI_OUT" | grep -qi "Unexpected error"; then
  say "  ✗ an unexpected error remains:"; printf '%s\n' "$TUI_OUT" | tail -5 | sed 's/^/      /'
  exit 1
fi
if printf '%s' "$TUI_OUT" | grep -q "Ask anything"; then
  say "  ✓ TUI initialised with TMPDIR=$TMPNEW — the input prompt rendered"
else
  say "  ? TUI produced no error, but the prompt banner was not seen in 20s."
  say "    That can happen on a slow cold start or a pty that does not answer terminal"
  say "    capability queries; the capture is at $DIAG. Not treating it as success."
  exit 1
fi

# ---------------------------------------------------------------------------
if [ "$APPLY" = "0" ]; then
  say ""
  say "NOT changed yet. This will add to $RC:"
  say "    $MARKER"
  say "    export TMPDIR=\"$TMPNEW\""
  say ""
  if [ ! -t 0 ]; then say "DRY RUN (not a terminal). Re-run interactively, or pass --apply."; exit 0; fi
  printf "  type APPLY to apply: "
  read -r c
  [ "$c" = "APPLY" ] || { say "cancelled — nothing changed."; exit 0; }
fi

# ---------------------------------------------------------------------------
step "Applying"
# ---------------------------------------------------------------------------
[ -f "$RC" ] || die "$RC not found"
if grep -qF "$MARKER" "$RC"; then
  say "  already present in $RC — nothing to add"
else
  cp -a "$RC" "$RC.bak-$(date +%Y%m%d-%H%M%S)"
  say "  backed up to $RC.bak-<ts>"
  {
    printf '\n%s\n' "$MARKER"
    printf '# opencode extracts a native OpenTUI .so into TMPDIR and dlopen()s it;\n'
    printf '# a noexec /tmp makes that fail with "failed to map segment from shared object".\n'
    printf 'export TMPDIR="%s"\n' "$TMPNEW"
  } >> "$RC"
  say "  appended to $RC"
fi

step "Verify in a NEW shell"
say "  exec bash -l   (or open a new terminal)"
say "  opencode"
echo
# $0 is literally "bash" when this runs as `bash -c "$(...)"`, so printing "$0" told the
# owner to run "bash --rollback", which does nothing. Print a command that works.
say "  Rollback (same fetch path, with --rollback):"
say "    cd /mnt/archie_brain && git fetch -q origin && bash -c \"\$(git show origin/opencode/feat-repair-bay-close-pr:scripts/fix_opencode_noexec_tmp.sh)\" --rollback"
