#!/usr/bin/env bash
# dump_bashrc_region.sh — show WHY ~/.bashrc stops (if it does) before the TMPDIR export.
# Prints line NUMBERS and structure only; values of anything secret-looking are masked.
REPORT="${1:-/mnt/archie_brain/.bashrc-region.txt}"
RC="$HOME/.bashrc"
EXP="$(grep -n 'export TMPDIR=' "$RC" 2>/dev/null | head -1 | cut -d: -f1)"
# `$((EXP:-0))` is a syntax error — arithmetic context does not take `:-`. Default once, here.
EXP="${EXP:-0}"; [ "$EXP" -gt 0 ] 2>/dev/null || EXP=0
{
  echo "== $RC (lines 1..$EXP) — structure, values masked =="
  n=0
  while IFS= read -r line; do
    n=$((n+1))
    [ "$n" -gt "$EXP" ] && break
    masked="$line"
    # never echo a value that could be a token
    case "$line" in
      *secret*|*token*|*bearer*|*KEY=*|*PASSWORD*|*_PWD*)
        masked="$(printf '%s' "$line" | sed -E 's/(=|:).*/\1<masked>/')" ;;
    esac
    printf '%4d  %s\n' "$n" "$masked"
  done < "$RC"
  echo
  echo "== early exits above the export =="
  head -n "$EXP" "$RC" 2>/dev/null | grep -nE '(^|[;&|[:space:]])return([[:space:];]|$)' | sed 's/^/  /'
  echo
  echo "== the codex secret line =="
  grep -n 'codex/mcp_bearer' "$RC" | sed -E 's/(cat )[^ ]*/\1<path-masked>/' | sed 's/^/  /'
} > "$REPORT" 2>&1
chmod 600 "$REPORT"
echo "wrote $REPORT"
