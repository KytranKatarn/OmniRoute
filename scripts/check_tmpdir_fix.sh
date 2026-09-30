#!/usr/bin/env bash
# check_tmpdir_fix.sh — is the TMPDIR fix present, and does sourcing ~/.bashrc set it?
# Changes nothing. Writes a report the agent can read.
REPORT="${1:-/mnt/archie_brain/.tmpdir-check.txt}"
{
  echo "at $(date -Is)"
  echo "== is the export in ~/.bashrc? =="
  grep -n 'TMPDIR' "$HOME/.bashrc" 2>/dev/null || echo "  (no TMPDIR in ~/.bashrc)"

  echo
  echo "== DOES SOURCING ~/.bashrc SET IT?  (the question that actually matters) =="
  # The earlier version printed \$TMPDIR as seen by THIS script. This script runs under
  # `bash -c`, which never sources .bashrc — so that number was always going to be unset
  # and proved nothing about the owner's interactive shell. Sourcing in a child is the
  # only way to find out whether the line is reachable from an interactive shell.
  OUT="$(bash -ic 'echo "  TMPDIR=${TMPDIR:-UNSET}"' 2>/dev/null | tr -d '\r')"
  echo "$OUT"

  echo
  echo "== is .bashrc early-returning before the export? =="
  # A common shape: [ -z "$PS1" ] && return, or `case $- in *i*) ;; *) return;; esac`.
  # Anything like that ABOVE line 136 would make the export unreachable in a
  # non-interactive-but-sourced shell.
  LINENO_EXPORT="$(grep -n 'export TMPDIR=' "$HOME/.bashrc" 2>/dev/null | head -1 | cut -d: -f1)"
  if [ -n "$LINENO_EXPORT" ]; then
    echo "  export is at line $LINENO_EXPORT"
    head -n "$LINENO_EXPORT" "$HOME/.bashrc" 2>/dev/null \
      | grep -nE '^\s*(return|\[ .* \] && return|case \$-)' | sed 's/^/    possible early exit: /' \
      || echo "    no early return found above it"
  else
    echo "  (no export found)"
  fi

  echo
  echo "== environment facts =="
  echo "  dir: $(ls -ld "${TMPDIR:-$HOME/.cache/opencode/tmp}" 2>/dev/null || echo MISSING)"
  echo "  /tmp: $(grep -E ' /tmp ' /proc/mounts 2>/dev/null | cut -d' ' -f4 || echo '?')"
} > "$REPORT" 2>&1
chmod 600 "$REPORT"
echo "wrote $REPORT"
